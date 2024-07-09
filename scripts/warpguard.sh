#!/bin/bash
ENDPOINTFILE='/home/andy/workspaces/cfwarp/result.csv'
HEARTBEATIP='1.1.1.1'
CFWARP_PEER_ID='bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo='
WARP_PRI_KEY='<cfwarp private key>'
WARP_RESERVED='<cfwarp routing id>'

trap 'exit' SIGINT
trap 'exit' SIGTERM

fetch_endpoint() {
  local file="$1"

  # 读取第二行
  local second_line=$(sed -n '2p' "$file")
  local endpoint=$(echo "$second_line"|cut -d',' -f1)

  # 输出endpoint
  echo "$endpoint"

  # 将第二行删除，这里使用 sed 命令来处理文件
  sed -i '2d' "$file"
}

ip_reachable() {
    local ip="$1" 

    # 使用 ping 命令检测 IP 地址
    # -c 1 表示发送一个数据包
    # -w 1 表示超时时间
    timeout 0.1s ping -c 1 "$ip" &> /dev/null

    # 检查上一条命令的退出状态码
    if [ $? -eq 0 ]; then
      # echo 'reachable'
      return 0  # IP 地址可达
    else
      # echo 'unreachable'
      return 1  # IP 地址不可达
    fi
}

rotate_endpoint(){
  local iface=$1
  local peerid=$2
  local endpoint=$(fetch_endpoint $ENDPOINTFILE)
  wg set $iface peer $peerid endpoint "$endpoint"
  if [ $? == 0 ]; then
    echo "[INFO] endpoint rotated, new endpoint: $endpoint"
  fi
}

load_endpoints(){
  local outfile=$1
  local nr_thrd=$2
  local nr_addr=$3
  local tmpfile="/tmp/result.csv.$$"
  /home/andy/workspaces/cfwarp/CloudflareWarpSpeedTest -ipv6 -o $tmpfile -n $nr_thrd -c $nr_addr -pri $WARP_PRI_KEY -reserved "$WARP_RESERVED" &> /dev/null
  mv $tmpfile $outfile
}

daemon(){
  while true; do
    
    if [[ ! -f $ENDPOINTFILE ]]; then
      load_endpoints $ENDPOINTFILE 1000 5000
    elif [ $(wc -l < $ENDPOINTFILE) -lt 100 ]; then
      load_endpoints $ENDPOINTFILE 1000 5000 &
    fi

    if ! ip_reachable $HEARTBEATIP ; then
      echo "[WARN] connection check failed, try to rotate endpoint"
      rotate_endpoint 'cfwarp' $CFWARP_PEER_ID
      sleep 5
    else
      # echo "[INFO] connection check succeeded" 
      sleep 1
    fi
    
    wait
  done
}

daemon

