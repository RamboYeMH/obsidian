连接:ssh ubuntu@192.168.1.204
跳板机连接
审核服分支：
1. cd ops/ansible 
2.  ./console.sh
3. env h5review //切换到h5环境
4. use 1 // 使用环境
5. vars //查看变量
6. deploy //部署某个包

**查看日志**



Last login: Tue Sep 1 22:09:20 2026 from 192.168.5.250 ubuntu@innerjumper:$ cd ops/ansible ubuntu@innerjumper:/ops/ansible$ ./console.sh input 'h' for help [revive] > env h5review [h5review] 
> use 1 [h5review] h5review> vars [tools] h5review ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' device=true

  

[gs] gdconfig ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=gdconfig id=1 gmt1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=gmt id=1 platform1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=platform id=1 webserver1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=webserver id=1 mail1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=mail id=1 chat1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=chat id=1 pay1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=pay id=1 gate1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=gate id=1 rank1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=rank id=1 door1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=door id=1 game1 ansible_user=ubuntu ansible_ssh_host=119.29.246.73 ansible_ssh_pass='[9kH5RsX=h?b' process=game id=1

  

[h5review] h5review>
