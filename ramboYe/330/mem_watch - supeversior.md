```
cc@rambo:/etc/supervisor/conf.d$ cat mem_watch.conf ; 内存监控 + 自动 pprof 采集 ; 脚本：/home/cc/slgh5/gs/scripts/mem_watch.py ; 触发条件：cross 任意实例内存 5 分钟内单调上涨且增长率 ≥ 5%

[program:mem_watch]
command=python3 /home/cc/slgh5/gs/scripts/mem_watch.py
directory=/home/cc/slgh5/gs
user=cc
autostart=true
autorestart=true
startsecs=5
startretries=3
redirect_stderr=true
stdout_logfile=/home/cc/slgh5/gs/log/mem_watch.out
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
stopasgroup=true
killasgroup=true
```

已启动运行（supervisor 管理，进程持久驻留在本机）。
