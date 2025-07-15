import click
import requests
import socket
import time
import logging
import signal
import sys
import netifaces as ni
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

# 全局变量来标记程序是否应该退出
running = True

def signal_handler(sig, frame):
    """处理终止信号的函数"""
    global running
    logging.getLogger('adguard-ddns').info("接收到终止信号，正在优雅退出...")
    running = False
    
def gracyful_sleep(seconds):
    """优雅地睡眠函数，检查是否收到终止信号"""
    global running
    for _ in range(seconds):
        if not running:
            break
        time.sleep(1)

@click.command()
@click.option('--interface', required=True, help='网络接口名称(例如: eth0)')
@click.option('--subnet', default="0.0.0.0/0", help='只有域名落在这个网段中的ip才会被使用(例如: 192.168.1.0/24)')
@click.option('--adguard-url', required=True, help='AdGuard Home 的完整 URL(例如: http://adguard.local:3000)')
@click.option('--adguard-user', required=True, help='AdGuard Home 用户名')
@click.option('--adguard-password', required=True, help='AdGuard Home 密码')
@click.option('--hostname', default=None, help='指定主机名(不指定时使用系统主机名)')
@click.option('--domain-suffix', default="" , help='附加到主机名的域名后缀')
@click.option('--interval', default=5, type=int, help='检查间隔时间（秒）')
@click.option('--dry-run', is_flag=True, help='启用 dry-run 模式，不会实际更新 AdGuard Home 的规则')
@click.option('--log-level', type=click.Choice(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], 
              case_sensitive=False), default='INFO', help='日志级别')
def update_adguard_rewrite(interface, subnet, adguard_url, 
                           adguard_user, adguard_password, hostname, domain_suffix, interval, dry_run, log_level):
    """
    定期检查指定网络接口在指定网段中的 IP 地址，并在 AdGuard Home 中更新相应的 rewrite 规则。
    """
    # 设置日志级别
    numeric_level = getattr(logging, log_level.upper(), None)
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger('adguard-ddns')
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 创建会话用于 AdGuard Home API 调用
    session = requests.Session()
    
    # 解析 AdGuard Home URL
    parsed_url = urlparse(adguard_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        logger.error("AdGuard Home URL 格式错误，请提供完整的 URL（例如：http://adguard.local:80）")
        return
    
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    credentials = {'name': adguard_user, 'password': adguard_password}
    auth_url = f"{base_url}/control/login"
    
    # 认证到 AdGuard Home
    response = session.post(auth_url, json=credentials)
    if response.status_code != 200:
        logger.error("AdGuard Home 认证失败！")
        return
    
    # 获取主机名(优先使用指定的主机名)
    host = hostname if hostname else socket.gethostname()
    full_domain = f"{host}.{domain_suffix}"
    
    # 解析目标网段
    try:
        target_net = ip_network(subnet)
    except ValueError as e:
        logger.error(f"网段格式错误：{e}")
        return
    
    # 修改主循环，使其在接收到信号时优雅退出
    global running
    running = True
    
    while running:
        try:
            # 获取指定接口的 IP 地址
            try:
                addrs = ni.ifaddresses(interface)
            except ValueError:
                logger.error(f"找不到接口 '{interface}'。可用接口：{ni.interfaces()}")
                break
            
            # 查找接口上的 IPv4 地址
            ips = []
            for addr in addrs.get(ni.AF_INET, []):
                ip = ip_address(addr['addr'])
                if ip in target_net:
                    ips.append(ip)
            
            # 检查是否找到匹配的 IP 地址
            if not ips:
                logger.warning(f"在 {interface} 接口上未找到 {subnet} 网段的 IP 地址")
                gracyful_sleep(interval)
                continue
            
            # 使用第一个匹配的 IP 地址
            current_ip = ips[0]
            logger.info(f"检测到 {interface} 接口上的 IP 地址：{current_ip}，属于 {subnet} 网段")
            
            # 准备 rewrite 规则数据
            update = {
                "domain": full_domain,
                "answer": str(current_ip),
            }
            
            # 获取现有的 rewrite 规则
            rules_url = f"{base_url}/control/rewrite/list"
            response = session.get(rules_url)
            
            if response.status_code == 200:
                existing_rules = response.json()
                
                # 检查规则是否已存在
                target = {"domain": full_domain, "answer": None}
                for rule in existing_rules:
                    if rule.get('domain').strip() == full_domain.strip():
                        answer =  rule.get('answer', '')
                        try:
                            target["answer"] = ip_address(answer)
                            break
                        except ValueError:
                            target["answer"] = None
                
                if target["answer"]:
                    # 检查 IP 是否发生变化
                    if target["answer"] == current_ip:
                        logger.info(f"IP 地址未更改 ({current_ip})，无需更新。")
                    else:
                        if dry_run:
                            logger.info(f"[DRY-RUN] 将更新 rewrite 规则：{full_domain} -> {current_ip}")
                        else:
                            # 使用 /rewrite/update API 更新规则
                            update_url = f"{base_url}/control/rewrite/update"

                            # prepare serializable target
                            
                            update_response = session.put(update_url, json={"target": {"domain": full_domain, "answer": str(target["answer"])}, "update": update})
                            
                            if update_response.status_code == 200:
                                logger.warning(f"更新 rewrite 规则成功：{full_domain} -> {current_ip}")
                            else:
                                logger.error(f"更新 rewrite 规则失败：{update_response.text}")
                else:
                    if dry_run:
                        logger.info(f"[DRY-RUN] 将创建新的 rewrite 规则：{full_domain} -> {current_ip}")
                    else:
                        # 创建新的规则
                        add_url = f"{base_url}/control/rewrite/add"
                        create_response = session.post(add_url, json=update)
                        
                        if create_response.status_code == 200:
                            logger.warning(f"创建新的 rewrite 规则：{full_domain} -> {current_ip}")
                        else:
                            logger.error(f"创建 rewrite 规则失败：{create_response.text}")
            else:
                logger.error(f"获取现有 rewrite 规则失败：{response.text}")
            
            # 如果收到终止信号，在完成当前循环后退出
            if not running:
                logger.info("完成当前处理后退出...")
                break
                
        except Exception as e:
            logger.error(f"发生错误：{str(e)}")
            if not running:
                break
        
        finally:
            gracyful_sleep(interval)
    logger.info("程序已正常退出")

if __name__ == '__main__':
    update_adguard_rewrite()
