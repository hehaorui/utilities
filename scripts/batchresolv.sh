#!/bin/bash
# vim: set filetype=bash shiftwidth=2 tabstop=2 expandtab:
# batchresolv.sh: perform batched dns resovle operation on the domain list read from stdin

fifo_file1="/tmp/$$.fifo"

mkfifo $fifo_file1
exec 6<>$fifo_file1
rm $fifo_file1

thread_num=5

ERRMSG=\
"Invalid argument, usage: domain2ip.sh [-doh] [-s SERVER] [-type {A|AAAA}] [-nthr THREAD_NUMBER]\n\
The domain list will be read from stdin"

regex4='(?:(?:1[0-9][0-9]\.)|(?:2[0-4][0-9]\.)|(?:25[0-5]\.)|(?:[1-9][0-9]\.)|(?:[0-9]\.)){3}(?:(?:1[0-9][0-9])|(?:2[0-4][0-9])|(?:25[0-5])|(?:[1-9][0-9])|(?:[0-9]))'
regex6='(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4})|(([0-9a-fA-F]{1,4}:){6}:[0-9a-fA-F]{1,4})|(([0-9a-fA-F]{1,4}:){5}(:[0-9a-fA-F]{1,4}){1,2})|(([0-9a-fA-F]{1,4}:){4}(:[0-9a-fA-F]{1,4}){1,3})|(([0-9a-fA-F]{1,4}:){3}(:[0-9a-fA-F]{1,4}){1,4})|(([0-9a-fA-F]{1,4}:){2}(:[0-9a-fA-F]{1,4}){1,5})|([0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6}))|(:((:[0-9a-fA-F]{1,4}){1,7})))'
regex="$regex4"

trap "kill -9 $$" SIGINT

# parse arguments
while (( $# > 0 ))
do
        case $1 in
                "-doh")
                        doh="+https"

                        if [ ! -n "$server" ];then
                                server="@1.1.1.1"
                        fi

                        shift
                        ;;
                "-s")
                        shift
                        server=@$1
                        shift
                        ;;
                "-type")
                        shift

                        if [ "$1" == "A" ];then
                                type="A"
                                regex="$regex4"

                        elif [ "$1" == "AAAA" ];then
                                type="AAAA"
                                regex="$regex6"

                        else
                                echo -e "$ERRMSG"
                                exit
                        fi

                        shift
                        ;;
                "-nthr")
                        shift
      if [[ ! "$1" =~ ^[0-9]+$ ]];then
        echo -e "$ERRMSG"
        exit
      elif (( $1<=0 ));then
        echo "bad argument, thread number should be positive"
        exit
      fi
      thread_num=$1
      shift
                        ;;
                *)
                        echo -e "$ERRMSG"
                        exit
                        ;;
        esac
done

#allocate token and output lock
for ((i=0;i<${thread_num};i++));do
  echo
done>&6

while IFS= read -r line
do
  read -u 6
  {
    dig +short $doh $line $server $type | grep -P -o "$regex"

    echo >&6
  }&
done

wait

exec 6>&-
