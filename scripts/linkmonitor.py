import time
import subprocess
import click
from datetime import datetime
import logging
import signal

# 配置日志
def configure_logging(log_level, log_file=None):
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'无效的日志级别: {log_level}')

    handlers = [logging.StreamHandler()]  # 默认输出到控制台

    if log_file:
        handlers.append(logging.FileHandler(log_file))  # 输出到指定文件

    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

logger = logging.getLogger('NetworkMonitor')

class NetworkMonitor:
    def __init__(self, upstreams, target_ips, table_id, interval, use_ecmp, dry_run=False):
        # 将上游信息分割为列表
        self.upstreams = map(
                            lambda x: {
                                p: v for p, v in 
                                zip(["interface", "gateway", "testip"], x.split(","))
                            }, 
                            upstreams
                        )
        self.target_ips = target_ips  # 路由表项的目标地址
        self.table_id = table_id
        self.interval = interval
        self.use_ecmp = use_ecmp
        self.dry_run = dry_run
        
        # 网卡状态记录
        self._interface_states = {upstream["interface"]: {'healthy': True, 'last_healthy': None} 
                                for upstream in self.upstreams}
        
        # 运行标志
        self.running = True
    
    def update_interface_state(self, interface, packet_loss):
        """更新网卡状态"""
        current_state = self._interface_states[interface]
        if packet_loss > 5:  # 丢包率超过5%视为断开连接
            if current_state['healthy']:
                # 状态由健康变为不健康
                current_state['healthy'] = False
                current_state['last_healthy'] = datetime.now()
                logger.warning(f"{interface} 到 {self.test_ip} 的丢包率为 {packet_loss}%, 连接断开")
        else:
            if not current_state['healthy']:
                # 状态由不健康变为健康
                current_state['healthy'] = True
                logger.info(f"{interface} 到 {self.test_ip} 的连接已经恢复")
    
    def get_healthy_interfaces(self):
        """获取当前健康的网卡列表"""
        healthy_interfaces = []
        for interface, state in self._interface_states.items():
            if state['healthy']:
                healthy_interfaces.append(interface)
        return healthy_interfaces
    
    def modify_route(self):
        """修改路由表"""
        try:
            healthy_interfaces = self.get_healthy_interfaces()
            
            if not healthy_interfaces:
                # 如果没有健康的网卡，不修改路由表
                logger.warning("没有健康的网卡，跳过路由表修改")
                return False
            
            for target_ip in self.target_ips:
                # 构建新的路由配置命令
                command = ['ip', 'route', 'replace', 'table', str(self.table_id), target_ip]

                if self.use_ecmp:
                    # ECMP模式处理
                    for interface in healthy_interfaces:
                        gateway = self.upstreams[interface]['gateway']
                        command += ['nexthop', 'via', gateway, 'dev', interface]
                else:
                    # 非ECMP模式处理
                    # 只使用第一个健康的网卡
                    interface = healthy_interfaces[0]
                    gateway = self.upstreams[interface]['gateway']
                    command += ['via', gateway, 'dev', interface, 'metric', '100']

                # 执行路由修改命令
                if not self.dry_run:
                    subprocess.check_call(command)
                    logger.info(f"已执行: {' '.join(command)}")
                else:
                    logger.info(f"[DRY-RUN] 会执行: {' '.join(command)}")
            
            return True
        except Exception as e:
            logger.error(f"修改路由表失败: {str(e)}")
            return False
    
    def run_check(self):
        """运行网卡连接检测"""
        processes = {}
        results = {}
        for upstream in self.upstreams:
            # 构建mtr命令
            command = [
                'mtr',
                '-r',  # 输出精简结果
                '-c', str(int(self.interval)),  # 发送的数据包数量
                '-i', '1',  # 设置发包间隔为1秒
                '-T',  # 使用 TCP 模式
                '-n', # 显示 IP 地址
                '-I', upstream["interface"],  # 指定网卡
                upstream['testip'],  # 测试IP
            ]
            # 启动子进程
            logger.debug(f"即将执行: {' '.join(command)}")
            processes[interface] = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # 等待所有子进程完成并获取结果
        for interface, process in processes.items():
            output, _ = process.communicate()
            lines = output.decode('utf-8').split('\n')  

            # 解析mtr输出结果，获取丢包率
            for line in reversed(lines):
                if self.upstreams[interface]['testip'] in line:
                    try:
                        packet_loss = float(line.split()[2].strip('%'))
                    except (ValueError, IndexError):
                        packet_loss = 100
                    break
            else:
                # 如果没有找到目标地址的丢包率信息，假设100%丢包
                packet_loss=100
          
            # 更新网卡状态
            self.update_interface_state(interface, packet_loss)
            results[interface] = packet_loss

        self.log_check_results(results)

    def log_check_results(self, results):
      """记录检测结果"""
      logger.info("检测结果:")
      for interface, packet_loss in results.items():
        status = "健康" if self._interface_states[interface]['healthy'] else "不健康"
        logger.info(f"  - {interface}: 丢包率 {packet_loss}%, 状态: {status}")
    
    def run(self):
        """启动监控循环"""
        try:
            while self.running:
                # 记录开始时间
                start_time = time.time()

                logger.info(f"检测周期开始")
                
                # 并发检测网卡连接状态
                self.run_check()
                
                # 修改路由表
                self.modify_route()
                
                # 计算本轮检测耗时
                elapsed_time = time.time() - start_time

                # 等待下一个检测周期
                if elapsed_time < self.interval:
                    sleep_time = self.interval - elapsed_time
                    for _ in range (int(sleep_time)):
                        if not self.running:
                          break
                        time.sleep(1)

                if not self.running:
                    break
                
        except Exception as e:
            logger.error(f"发生错误: {str(e)}")
        finally:
            logger.info("监控已停止")

def signal_handler(signum, frame):
    """信号处理程序"""
    logger.info(f"收到信号 {signum}, 停止监控...")
    if hasattr(monitor, 'running'):
        monitor.running = False

# 全局变量，用于在信号处理程序中访问监控实例
monitor = None

# 使用click库定义命令行参数
@click.command()
@click.option('--upstream', '-u', help='要监控的出口，形式: <interface>,<gateway>,<test-ip>,', required=True, multiple=True)
@click.option('--target-ip', '-T', help='路由表项的目标地址 (可多次指定)', required=True, multiple=True)
@click.option('--table-id', '-r', help='路由表ID', type=int, default=254, show_default=True)
@click.option('--interval', '-I', help='检测间隔时间 (秒)', type=float, default=5.0, show_default=True)
@click.option('--use-ecmp', '-e', help='是否使用ECMP模式', is_flag=True)
@click.option('--dry-run', '-d', help='启用dry-run模式, 只模拟不执行', is_flag=True)
@click.option('--log-level', '-l', help='日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)', default='INFO', show_default=True)
@click.option('--log-file', '-L', help='日志文件路径 (不提供此参数则不保存日志到文件)', type=str, default=None)
def main(upstream, target_ip, table_id, interval, use_ecmp, dry_run, log_level, log_file):
    """启动网络监控脚本"""
    global monitor
    
    # 配置日志
    configure_logging(log_level, log_file)
    
    # 创建监控实例
    monitor = NetworkMonitor(upstream, target_ip, table_id, interval, use_ecmp, dry_run)
    
    # 注册信号处理程序
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动监控
    monitor.run()

if __name__ == '__main__':
    main()
