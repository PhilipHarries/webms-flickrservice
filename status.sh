sudo netstat -npa|grep 5433|grep LISTEN|awk '{print $NF}'|sed s%/python%%
