#!/usr/bin/env python3
"""交互式部署 benchmark；本文件内置全部模板，可单独复制到目标 Linux Docker 主机运行。

python3 benchmark-deploy.py                     # 交互收集、检查、初始化、启动
python3 benchmark-deploy.py --prepare-only      # 只生成文件并校验 Compose
python3 benchmark-deploy.py --check --dir PATH  # 读取已保存参数，只读检查远端依赖
python3 benchmark-deploy.py --upgrade --dir PATH  # 更新本机旧部署，自动切换并在失败时回退
python3 benchmark-deploy.py --upgrade-worker --dir PATH  # 仅更新 Worker，其他三个服务保持运行
python3 benchmark-deploy.py --stop --dir PATH   # 检查任务已排空后关闭已有四服务，保留容器和数据
python3 benchmark-deploy.py --start --dir PATH  # 启动已有四服务并验收，不拉镜像或更新配置
python3 benchmark-deploy.py --local-image --dir PATH  # 使用本机已有镜像，不拉取

不传 --dir 时，部署目录默认是当前工作目录下的 config。
使用之前的参数重新部署（不是只读检查，不加 --check）：
python3 benchmark-deploy.py --dir "$HOME/benchmark/h5"
把示例目录换成首次部署时保存配置的实际目录，里面应有 deploy-settings.json。
脚本会把旧参数作为默认值；逐项按回车保留，最后输入 yes 执行重新部署。
检测到本机旧部署会进入更新流程；无需预先手动停止或重启容器。
运行任务和自动投放须先在管理台暂停；脚本不会强杀任务或停止其他机器上的服务。
普通升级复用原共享配置，数据库/NATS 迁移、协议和存档迁移不属于自动升级范围。
完整更新默认停服后覆盖原配置库（必须为本部署专用）；失败时从旧镜像重新导入配置再恢复服务。
仅更新 Worker 适用于游戏协议等兼容更新，复用原配置库；仍须先停止任务、停用自动投放并排空会话。

前提：Python 3.8+、Docker Engine、Compose v2（docker compose 或 docker-compose）；Mongo 副本集、NATS JetStream、etcd
已可用。依赖可以分别位于任意机器，地址必须从 Docker 容器可达。
镜像须为 Jenkins benchmark+gdconfig 组合镜像，含 Python/pymongo 和 /k1。
沿用当前程序能力：etcd 无认证入口；自定义 CA/客户端证书挂载暂不支持。
脚本不安装或重启共享依赖，不创建机器人任务，不提交文件或推送镜像。
"""

import sys

if sys.version_info < (3, 8):
    print('需要 Python 3.8 或更高版本，请先升级 Python。', file=sys.stderr)
    sys.exit(1)

import argparse
import base64
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

AUTO_DEFAULTS = False
AUTO_CONFIRM = False


COMPOSE = r'''name: ${COMPOSE_PROJECT_NAME:?}
x-image: &image ${BENCHMARK_IMAGE:?}
x-env: &runtime-env
  TZ: Asia/Shanghai
  BENCHMARK_ETCD_ENDPOINTS: ${BENCHMARK_ETCD_ENDPOINTS:?}
  BENCHMARK_ETCD_RUNTIME_CONFIG_ROOT: ${BENCHMARK_ETCD_RUNTIME_CONFIG_ROOT:?}
x-common: &common
  image: *image
  pull_policy: never
  restart: unless-stopped
  extra_hosts: ["host.docker.internal:host-gateway"]
  logging:
    driver: json-file
    options: {max-size: "20m", max-file: "5"}
x-health: &health
  interval: 10s
  timeout: 3s
  retries: 3
  start_period: 30s
services:
  robot-jetstream-provision:
    <<: *common
    restart: "no"
    profiles: [init]
    entrypoint: [/app/bin/robot_jetstream_provision]
    command: [check]
    environment:
      <<: *runtime-env
      ROBOT_NATS_URL: ${ROBOT_NATS_URL:?}
      ROBOT_PROCESS_ENVIRONMENT_ID: ${ROBOT_PROCESS_ENVIRONMENT_ID:?}
      ROBOT_JETSTREAM_REPLICAS: "1"
      ROBOT_MONGO_URI: ${BENCHMARK_DBURL:?}
      ROBOT_MONGO_DATABASE: ${BENCHMARK_DBNAME:?}
  benchmark:
    <<: *common
    ports: ["${MANAGER_BIND_IP:?}:${MANAGER_PORT:?}:18082"]
    environment:
      <<: *runtime-env
      ROBOT_PROCESS_ENVIRONMENT_ID: ${ROBOT_PROCESS_ENVIRONMENT_ID:?}
      BENCHMARK_HTTPADDR: ":18082"
      BENCHMARK_DBMOD: db
      BENCHMARK_DBURL: ${BENCHMARK_DBURL:?}
      BENCHMARK_DBNAME: ${BENCHMARK_DBNAME:?}
      BENCHMARK_CSV: ${BENCHMARK_CSV:?}
      BENCHMARK_GATEADDR: ${BENCHMARK_GATEADDR:?}
      BENCHMARK_SERVERID: ${BENCHMARK_SERVERID:?}
      BENCHMARK_ENVIRONMENT_SECRET_KEY: ${BENCHMARK_ENVIRONMENT_SECRET_KEY:?}
      BENCHMARK_LOGFILE: stdout
      BENCHMARK_LOGLEVEL: info
      BENCHMARK_USECONF: "1"
      BENCHMARK_DEV_AUTH_BYPASS: ${BENCHMARK_DEV_AUTH_BYPASS:?}
      BENCHMARK_WEBAUTH_ENABLED: "false"
      BENCHMARK_BLOCK_TEST_ENABLED: "${BENCHMARK_BLOCK_TEST_ENABLED:-false}"
      BENCHMARK_BLOCK_TEST_ENVIRONMENTS: "${BENCHMARK_BLOCK_TEST_ENVIRONMENTS:-test,local}"
      BENCHMARK_BLOCK_TEST_GM_ENVIRONMENTS: "${BENCHMARK_BLOCK_TEST_GM_ENVIRONMENTS:-test,local}"
      PORTAL_URL: ${PORTAL_URL:-}
      PORTAL_APP_ID: ${PORTAL_APP_ID:-}
      PORTAL_CALLBACK_URL: ${PORTAL_CALLBACK_URL:-}
      AUTH_COOKIE_SECURE: ${AUTH_COOKIE_SECURE:-true}
    healthcheck:
      <<: *health
      test: [CMD, curl, --fail, --silent, --max-time, "2", "http://127.0.0.1:18082/ping"]
  robot-worker:
    <<: *common
    stop_grace_period: 30s
    entrypoint: [/app/bin/robot_worker]
    environment:
      <<: *runtime-env
      ROBOT_PROCESS_ENVIRONMENT_ID: ${ROBOT_PROCESS_ENVIRONMENT_ID:?}
      ROBOT_WORKER_ID: ${ROBOT_WORKER_ID:?}
      ROBOT_WORKER_BUILD_VERSION: ${ROBOT_WORKER_BUILD_VERSION:?}
      ROBOT_WORKER_DATA_DIR: /var/lib/robot-worker
      ROBOT_CSV_DATABASE: ${BENCHMARK_CSV:?}
      BENCHMARK_ENVIRONMENT_SECRET_KEY: ${BENCHMARK_ENVIRONMENT_SECRET_KEY:?}
    volumes: ["worker-data:/var/lib/robot-worker"]
    healthcheck:
      <<: *health
      test: [CMD, curl, --fail, --silent, --max-time, "2", "http://127.0.0.1:18083/readyz"]
  robot-event-processor:
    <<: *common
    entrypoint: [/app/bin/robot_event_processor]
    environment: *runtime-env
    healthcheck:
      <<: *health
      test: [CMD, curl, --fail, --silent, --max-time, "2", "http://127.0.0.1:18084/livez"]
  robot-runtime-log-processor:
    <<: *common
    entrypoint: [/app/bin/robot_runtime_log_processor]
    environment: *runtime-env
    healthcheck:
      <<: *health
      test: [CMD, curl, --fail, --silent, --max-time, "2", "http://127.0.0.1:18085/livez"]
volumes:
  worker-data:
    external: true
    name: ${WORKER_VOLUME:?}
networks:
  default:
    external: true
    name: ${DEPLOY_NETWORK:?}
'''

# 在目标镜像的临时容器内执行：检查路径与真实服务保持同一 Docker 网络。
# 参数经 stdin 传入，不将 Mongo 密码放到命令行或输出。
HELPER = r'''
import base64, contextlib, datetime, hashlib, io, json, os, runpy, socket, sys, time
import urllib.request, urllib.error
from urllib.parse import urlsplit
from pymongo import MongoClient
from bson.int64 import Int64
from bson import json_util

c = json.load(sys.stdin)
action = sys.argv[1]
def require(ok, message):
    if not ok: raise RuntimeError(message)
def enc(s): return base64.b64encode(s.encode()).decode()
def etcd(method, payload):
    errors=[]
    for endpoint in c['etcd'].split(','):
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for api in ('v3','v3beta','v3alpha'):
                req=urllib.request.Request(endpoint.rstrip('/')+'/'+api+'/kv/'+method,
                    data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                try:
                    with opener.open(req,timeout=8) as r: result=json.load(r)
                    break
                except urllib.error.HTTPError as e:
                    if e.code==404 and api!='v3alpha': continue
                    raise
            require('error' not in result,'etcd 返回错误')
            return result
        except Exception as e: errors.append(type(e).__name__+':'+str(getattr(e,'code','')))
    raise RuntimeError('etcd v3 HTTP gateway 不可达或拒绝访问：'+','.join(errors))
def kv(key):
    return etcd('range',{'key':enc(key)}).get('kvs',[])
def check_instances():
    prefix=c['root']+'/instances/'
    items=etcd('range',{'key':enc(prefix),'range_end':enc(prefix[:-1]+'0')}).get('kvs',[])
    for item in items:
        instance=json.loads(base64.b64decode(item['value']))
        require(instance.get('instance_id') in c.get('own_instances',[]),
                '该 etcd 前缀已有其他部署的在线实例，拒绝启动第二套 Manager')
def snapshot(compare=True):
    current=kv(c['root']+'/current')
    if not current:
        require(not kv(c['root']+'/revisions/00000000000000000001'),
                '存在孤立 revision，停止自动初始化；请检查该 etcd 前缀')
        return None
    rev=int(base64.b64decode(current[0]['value']).decode())
    item=kv(c['root']+'/revisions/'+str(rev).zfill(20))
    require(bool(item),'current 指向不存在的 revision')
    data=json.loads(base64.b64decode(item[0]['value']))
    require(data.get('schema_version')==1 and data.get('revision')==rev,'快照版本结构不一致')
    differences=[]
    if compare:
        for section, fields in c['snapshot']['fields'].items():
            for name, value in fields.items():
                if data.get('fields',{}).get(section,{}).get(name)!=value:
                    differences.append(section+'.'+name)
    require(not differences,'已有 etcd 配置不一致：'+', '.join(differences)+'；未覆盖。更新本机旧部署请使用 --upgrade')
    return data
def connect():
    client=MongoClient(c['mongo'],serverSelectionTimeoutMS=8000,connectTimeoutMS=5000,
                       socketTimeoutMS=30000,tz_aware=True)
    h=client.admin.command('hello')
    require(h.get('setName') and h.get('isWritablePrimary'),'Mongo 必须是可写副本集；请管理员配置后重试')
    server_time=h['localTime']
    if server_time.tzinfo is None: server_time=server_time.replace(tzinfo=datetime.timezone.utc)
    skew=abs((server_time-datetime.datetime.now(datetime.timezone.utc)).total_seconds())
    require(skew<30,'部署机与 Mongo 服务端时钟偏差超过 30 秒')
    return client,h,skew
def manifest(db):
    want={'build_version':c['build'],'protocol_version':1,'state_machine_version':1,
          'required_indexes':['uq_session_id','idx_session_worker_assignment']}
    item=db.bm_robot_worker_manifests.find_one({'environment_id':c['environment']})
    if item:
        for k,v in want.items():
            require(item.get(k)==v,'已有 manifest 不兼容：'+k+
                    '，数据库值='+str(item.get(k))+'，本次值='+str(v)+'，未覆盖')
        require(item.get('revision',0)>0,'已有 manifest revision 非法')
    return item,want
def upgrade_idle(db):
    require(not db.bm_robot_task_runs.find_one({'status':'running'}),
            '仍有运行态任务，请先在管理台停止或排空任务；脚本不会强杀任务')
    require(not db.bm_robot_new_server_rules.find_one({'enabled':True}),
            '仍有启用的自动投放规则，请先在管理台暂停，避免切换期间创建新任务')
    require(not db.bm_robot_sessions.find_one({'status':{'$in':['connecting','online','logging_out']}}),
            '仍有连接中或未退出的机器人会话，请等待管理台排空后再更新')
    require(not db.bm_robot_sessions.find_one({'active_guard':True}),
            '仍有未收尾的机器人会话（含待调度会话），请等待管理台完成收尾后再更新')
def main():
    client,h,skew=connect(); db=client[c['database']]; cfg=client[c['csv']]
    if action=='stop_preflight':
        check_instances()
        upgrade_idle(db)
        return {'idle':True}
    if action=='start_preflight':
        check_instances()
        item,_=manifest(db)
        require(bool(item),'缺少 Worker manifest，请先完成部署')
        require(bool(snapshot(compare=False)),'缺少运行配置，请先完成部署')
        return {'compatible':True}
    if action=='upgrade_state':
        upgrade_idle(db)
        record=db.bm_robot_worker_manifests.find_one({'environment_id':c['environment']})
        require(bool(record),'旧环境缺少 manifest，无法自动升级')
        for key,value in {'protocol_version':1,'state_machine_version':1,
                          'required_indexes':['uq_session_id','idx_session_worker_assignment']}.items():
            require(record.get(key)==value,'当前模板不支持该兼容性迁移：'+key)
        require(record.get('revision',0)>0 and record.get('build_version'),'旧 manifest 不完整')
        state=snapshot(compare=False)
        require(bool(state),'旧环境缺少 etcd 运行快照')
        owner=db['_benchmark_deployments'].find_one({'_id':c['environment']})
        if owner:
            require(owner.get('secret_hash')==hashlib.sha256(c['secret'].encode()).hexdigest(),
                    '现有环境密钥指纹不匹配，拒绝升级')
        return {'snapshot':state,'manifest_ejson':json_util.dumps(record,json_options=json_util.CANONICAL_JSON_OPTIONS),
                'build_version':record['build_version'],'manifest_revision':int(record['revision'])}
    if action in ('upgrade_manifest','restore_manifest'):
        check_instances()
        old=json_util.loads(c['upgrade_manifest_ejson'],json_options=json_util.JSONOptions(tz_aware=True))
        collection=db.bm_robot_worker_manifests
        if action=='upgrade_manifest':
            upgrade_idle(db)
            require(snapshot(compare=False)==c['snapshot'],'预检后 etcd 配置发生变化，停止升级')
            current=collection.find_one({'_id':old['_id']})
            require(current==old,'预检后 manifest 发生变化，未覆盖')
            if old['build_version']==c['build']:return {'manifest':'版本不变，无需改写'}
            result=collection.update_one({'_id':old['_id'],'revision':old['revision'],'build_version':old['build_version']},
                {'$set':{'build_version':c['build'],'updated_at':datetime.datetime.now(datetime.timezone.utc),
                         'deployment_operation_id':c['upgrade_token']},'$inc':{'revision':Int64(1)}})
            require(result.modified_count==1,'manifest 已被其他操作修改，未覆盖')
            return {'manifest':'已切换新版本','revision':int(old['revision'])+1}
        current=collection.find_one({'_id':old['_id']})
        if current==old:return {'manifest':'旧记录未变，无需回退'}
        require(current and current.get('deployment_operation_id')==c['upgrade_token'],
                'manifest 不属于本次升级，停止自动回退')
        result=collection.replace_one({'_id':old['_id'],'revision':old['revision']+1,
            'build_version':c['build'],'deployment_operation_id':c['upgrade_token']},old)
        require(result.modified_count==1,'manifest 回退发生并发冲突，未覆盖')
        return {'manifest':'已恢复原记录'}
    if action=='manifest_info':
        item=db.bm_robot_worker_manifests.find_one({'environment_id':c['environment']})
        return {'database':c['database'],'environment_id':c['environment'],
                'manifest':{k:item.get(k) for k in ('build_version','protocol_version',
                    'state_machine_version','required_indexes','revision')} if item else None}
    if action=='instances':
        prefix=c['root']+'/instances/'
        items=etcd('range',{'key':enc(prefix),'range_end':enc(prefix[:-1]+'0')}).get('kvs',[])
        instances=[]
        for item in items:
            instance=json.loads(base64.b64decode(item['value']))
            instance['lease_status']='fresh' if int(item.get('lease',0)) else 'missing'
            instance['config_status']='aligned' if (
                instance.get('desired_config_revision')==instance.get('applied_config_revision')
                and instance.get('applied_config_revision',0)>0
                and not instance.get('restart_required')) else 'pending'
            instances.append(instance)
        return {'instances':instances}
    if action=='probe':
        require(not db.bm_robot_task_runs.find_one({'status':'running'}),
                '业务库仍有运行态任务，请在管理台停止任务后再部署')
        old,_=manifest(db)
        with client.start_session() as session:
            session.start_transaction()
            db.bm_robot_worker_manifests.find_one({},session=session)
            session.abort_transaction()
        existing=snapshot()
        check_instances()
        u=urlsplit(c['nats'])
        try:
            with socket.create_connection((u.hostname,u.port),timeout=5): pass
        except OSError as e: raise RuntimeError('容器无法连接 NATS：'+type(e).__name__) from e
        gate_ready=True
        u=urlsplit('tcp://'+c['gate'])
        try:
            with socket.create_connection((u.hostname,u.port),timeout=5): pass
        except OSError: gate_ready=False
        return {'replica_set':h['setName'],'clock_skew_seconds':round(skew,3),
                'business_collections':len(db.list_collection_names()),
                'config_collections':len(cfg.list_collection_names()),
                'manifest_exists':bool(old),'snapshot_exists':bool(existing),'gate_reachable':gate_ready,
                'owner_secret_hash':(db['_benchmark_deployments'].find_one(
                    {'_id':c['environment']}) or {}).get('secret_hash')}
    if action=='claim':
        records=db['_benchmark_deployments']
        want=hashlib.sha256(c['secret'].encode()).hexdigest()
        item=records.find_one({'_id':c['environment']})
        if not item:
            records.insert_one({'_id':c['environment'],'secret_hash':want,'project':c['project']})
            item=records.find_one({'_id':c['environment']})
        require(item.get('secret_hash')==want and item.get('project')==c['project'],
                '该环境已有不同密钥或部署标识，拒绝覆盖')
        return {'owner':'已核对环境密钥指纹与项目身份'}
    if action=='seed':
        if snapshot(): return {'snapshot':'已存在且一致'}
        current=c['root']+'/current'; revision=c['root']+'/revisions/00000000000000000001'
        result=etcd('txn',{'compare':[
            {'key':enc(current),'target':'VERSION','version':'0'},
            {'key':enc(revision),'target':'VERSION','version':'0'}],
            'success':[{'request_put':{'key':enc(revision),'value':enc(json.dumps(c['snapshot']))}},
                       {'request_put':{'key':enc(current),'value':enc('1')}}], 'failure':[]})
        require(result.get('succeeded'),'etcd 前缀被其他部署写入，已停止，请重新检查')
        return {'snapshot':'已事务性写入 revision 和 current'}
    if action=='manifest':
        _,want=manifest(db)
        db.bm_robot_worker_manifests.create_index('environment_id',unique=True,
                                                name='uq_robot_worker_manifest_environment')
        want.update(revision=Int64(1),updated_at=datetime.datetime.now(datetime.timezone.utc))
        db.bm_robot_worker_manifests.update_one({'environment_id':c['environment']},
                                              {'$setOnInsert':want},upsert=True)
        manifest(db)
        return {'manifest':'已核对 / 初始化'}
    if action=='config_source':
        require(os.path.isfile('/k1/scripts/update_meta.py') and all(os.path.isdir(p) for p in
            ('/k1/tsv','/k1/tsv/RandomMapUnit','/k1/tsv/MapNpcRefreshPoint')),
            '镜像缺少配置导入脚本或 TSV 目录，不能更新或恢复配置')
        return {'config_source':'配置导入资源存在'}
    if action in ('import','replace_config'):
        replacing=action=='replace_config'
        if replacing:
            require(c['csv'].startswith('gs_conf_') and c['csv']!=c['database'],
                    '只允许覆盖独立配置库，禁止改写业务库')
            require(c.get('replace_config_database')==c['csv'], '未确认覆盖该部署专用配置库')
            require(not c.get('own_instances'), '覆盖配置前必须停止全部服务')
            check_instances()
            upgrade_idle(db)
        marks=db['_benchmark_deploy_config_imports']
        record=marks.find_one({'_id':c['csv']})
        if not replacing and c['config_mode']=='reuse':
            require(bool(cfg.list_collection_names()),'选择复用的配置库为空')
            return {'config':'复用已有库，未改写','collections':len(cfg.list_collection_names())}
        if not replacing and record and record.get('state')=='ready':
            require(record.get('image')==c['image'],'配置库对应另一镜像；请换新库或明确选择复用')
            require(bool(cfg.list_collection_names()),'导入记录存在，但配置库已为空')
            return {'config':'此前已导入同一镜像，跳过','collections':len(cfg.list_collection_names())}
        if not replacing:
            require(not record,'上次导入未成功，请检查后换新配置库；不会自动覆盖部分导入数据')
            require(not cfg.list_collection_names(),'目标配置库非空；请选择复用或换新库')
        marks.update_one({'_id':c['csv']},{'$set':{'state':'loading','image':c['image']}},upsert=True)
        # 只允许原导入脚本删除已确认的专用配置库一次；首次导入仍要求空库。
        # 无需解析 URI 交给旧参数逻辑，使用已验证的 MongoClient（含认证和副本集参数）。
        import pymongo
        dropped=False
        class GuardClient:
            def __getitem__(self,name):
                require(name==c['csv'],'导入程序尝试访问非目标配置库')
                return cfg
            def drop_database(self,name):
                nonlocal dropped
                require(name==c['csv'] and not dropped,'拒绝删除非目标库或重复删除配置库')
                if replacing:
                    client.drop_database(name)
                else:
                    require(not cfg.list_collection_names(),'目标配置库已出现数据，拒绝删除')
                dropped=True
        original=pymongo.MongoClient
        pymongo.MongoClient=lambda *a,**k: GuardClient()
        output=io.StringIO()
        try:
            sys.argv=['update_meta.py','-t',c['csv'][len('gs_conf_'):],'-d','deployment-managed']
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output):
                runpy.run_path('/k1/scripts/update_meta.py',run_name='__main__')
            lines=output.getvalue().splitlines()
            errors=[line for line in lines if 'failed' in line.lower()
                    and 'documents must be a non-empty list' not in line]
            require(not errors and 'update success!' in lines,'配置导入未完成或存在非空表错误')
            require(cfg.ADShopCfg.count_documents({})>0,'关键配置 ADShopCfg 为空')
            marks.update_one({'_id':c['csv']},{'$set':{'state':'ready'}})
            return {'config':'原库覆盖成功' if replacing else '导入成功','collections':len(cfg.list_collection_names()),
                    'empty_tables':sum('documents must be a non-empty list' in x for x in lines)}
        except BaseException:
            marks.update_one({'_id':c['csv']},{'$set':{'state':'failed'}})
            raise
        finally: pymongo.MongoClient=original
    raise RuntimeError('未知检查动作')
try:
    print(json.dumps({'ok':True,'result':main()},ensure_ascii=False))
except BaseException as e:
    # 驱动错误可能含密码，先脱敏再返回；不输出 traceback 或参数对象。
    message=str(e)
    for key in ('mongo','nats','secret'):
        value=c.get(key,'')
        if value: message=message.replace(value,'<已隐藏>')
    for key in ('mongo','nats'):
        try:
            password=urlsplit(c[key]).password
            if password: message=message.replace(password,'<已隐藏>')
        except ValueError: pass
    print(json.dumps({'ok':False,'error':type(e).__name__+': '+message},ensure_ascii=False))
    sys.exit(1)
'''


class DeployError(Exception):
    pass


def ask(label, default='', secret=False):
    if AUTO_DEFAULTS:
        if default:
            return default
        raise DeployError('本地非交互部署缺少必填预设：'+label)
    # 按操作者要求，所有填写项均可见，便于核对；不额外写入日志。
    hint = f' [{default}]' if default else ''
    while True:
        try:
            value = input(label + hint + ': ').strip() or default
            if any(ch in value for ch in '\r\n\x00'):
                raise ValueError('输入不能包含换行或空字符')
            value.encode('utf-8')
            return value
        except UnicodeError:
            print('输入包含无效编码，请重新输入本项（终端使用 UTF-8）。')
        except ValueError as exc:
            print(str(exc)+'，请重新输入本项。')


def required(label, default='', secret=False, validator=None, optional=False):
    if AUTO_DEFAULTS:
        value=default
        if not value and not optional:
            raise DeployError('本地非交互部署缺少必填预设：'+label)
        if value and validator:
            validator(value)
        return value
    while True:
        value = ask(label, default, secret)
        if value or optional:
            if validator:
                try:
                    validator(value)
                except (ValueError, DeployError) as exc:
                    print('填写格式不正确：'+str(exc)+'。请重新填写本项。')
                    default=''
                    continue
            return value
        print('此项必填。')


def yes(label):
    if AUTO_DEFAULTS:
        if label == '确认执行上述部署':
            return AUTO_CONFIRM
        raise DeployError('本地非交互部署拒绝未预期的确认步骤：'+label)
    return ask(label + '，输入 yes 继续', 'no').lower() == 'yes'


def run(args, *, data=None, timeout=120, check=True, capture=True):
    result = subprocess.run(args, input=data, text=True, encoding='utf-8', errors='replace',
                            capture_output=capture, timeout=timeout)
    if check and result.returncode:
        # 不输出可能包含私有环境变量的原始命令或 Docker stderr。
        raise DeployError(f'{Path(args[0]).name} 执行失败（退出码 {result.returncode}）')
    return result


def private_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def endpoint(value, scheme, label):
    parsed = urlsplit(value if '://' in value else scheme + '://' + value)
    try:
        port = parsed.port
    except ValueError as e:
        raise DeployError(f'{label} 端口无效') from e
    if not parsed.hostname or not port or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise DeployError(f'{label} 必须是明确的主机名/IP 和端口')
    if parsed.hostname == 'localhost':
        raise DeployError(f'{label} 不能用 localhost；请填写容器可达的地址')
    try:
        if ipaddress.ip_address(parsed.hostname).is_loopback:
            raise DeployError(f'{label} 不能用回环地址；它在容器中指向容器自身')
    except ValueError:
        pass
    return parsed


def pattern(value, expression, message):
    if not re.fullmatch(expression,value):
        raise DeployError(message)


def number(value, maximum, label):
    if not value.isdecimal() or not 1<=int(value)<=maximum:
        raise DeployError(f'{label} 必须是 1–{maximum} 的整数')


def mongo_uri(value):
    if value.startswith('mongodb://'):
        authority=value[len('mongodb://'):].split('/',1)[0].rsplit('@',1)[-1]
        for host in authority.split(','):
            endpoint(host if ':' in host else host+':27017','tcp','Mongo')
    elif value.startswith('mongodb+srv://'):
        if not urlsplit(value).hostname:
            raise DeployError('Mongo SRV URI 缺少主机名')
    else:
        raise DeployError('例如 mongodb://10.0.0.10:27017/?replicaSet=rs0，须包含 mongodb:// 或 mongodb+srv://')


def nats_url(value):
    if '://' not in value:
        raise DeployError('须包含协议，例如 nats://10.0.0.20:4222')
    if endpoint(value,'nats','NATS').scheme not in ('nats','tls'):
        raise DeployError('NATS URL 须使用 nats:// 或 tls://')


def etcd_endpoints(value):
    for item in value.split(','):
        ep=endpoint(item.strip(),'http','etcd')
        if ep.scheme!='http' or ep.username or ep.password:
            raise DeployError('例如 http://10.0.0.30:2379；当前支持无认证 HTTP 入口')


def gate_address(value):
    if '://' in value or '@' in value:
        raise DeployError('Gate 只填 host:port，例如 10.0.0.40:21001')
    endpoint(value,'tcp','Gate')


def etcd_root(value):
    if not value.startswith('/') or value.endswith('/') or value=='/' or any(x.isspace() for x in value):
        raise DeployError('例如 /benchmark/h5/docker/runtime-config，以 / 开头，不以 / 结尾，不含空格')


def choice(value, values):
    if value not in values:
        raise DeployError('只能填写 '+ ' 或 '.join(values)+'，不要填写序号')


def web_url(value):
    u=urlsplit(value)
    if u.scheme not in ('http','https') or not u.hostname:
        raise DeployError('须填写完整 http:// 或 https:// 地址')


def image_reference(value):
    if not value or any(x.isspace() for x in value) or value.startswith('-'):
        raise DeployError('镜像引用不能为空、包含空白或以 - 开头')


def environment_secret(value):
    if value:
        try:
            if len(base64.b64decode(value,validate=True))!=32:
                raise ValueError()
        except ValueError as exc:
            raise DeployError('环境密钥必须是32字节的 Base64（通常44字符）；新库可留空生成') from exc


def config_database(value, database):
    pattern(value,r'gs_conf_[a-zA-Z0-9_-]{1,55}','配置库名须以 gs_conf_ 开头，例如 gs_conf_benchmark_h5')
    if value==database:
        raise DeployError('配置库不能与 benchmark 业务库同名')


def validate(c):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', c['environment']):
        raise DeployError('环境 ID 使用小写字母开头的字母、数字、下划线或连字符，最长40字符')
    for key in ('database', 'csv'):
        if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,62}', c[key]):
            raise DeployError(f'{key} 库名不合法')
    if not c['csv'].startswith('gs_conf_') or c['csv']=='gs_conf_' or c['csv'] == c['database']:
        raise DeployError('配置库须以 gs_conf_ 开头，且与业务库不同')
    etcd_root(c['root'])
    image_reference(c['image'])
    mongo_uri(c['mongo'])
    nats_url(c['nats'])
    gate_address(c['gate'])
    etcd_endpoints(c['etcd'])
    if c['config_mode'] not in ('import','reuse'):
        raise DeployError('配置库模式只能为 import 或 reuse')
    if not 1 <= int(c['port']) <= 65535 or int(c['server']) <= 0:
        raise DeployError('管理台端口或区服 ID 无效')
    ipaddress.IPv4Address(c['bind'])
    if c['auth'] not in ('bypass','portal'):
        raise DeployError('认证模式只能为 bypass 或 portal')
    if c['auth']=='portal':
        for k in ('portal_url','portal_app','portal_callback'):
            if not c.get(k): raise DeployError('Portal 模式必须填写 URL、App ID 和 Callback URL')
    environment_secret(c.get('secret',''))


def collect(old):
    c=dict(old)
    print('\n按提示逐项填写；输入均可见，不替你选择。方括号是默认值，按回车才接受。')
    print('所有示例 IP、域名和版本均需按实际环境替换，不是自动探测结果。')
    print('\n镜像：例如 harbor-dev.330stars.com/gs/gs-benchmark:20261008-183245。')
    print('如用 --local-image 启动，也可填写本机镜像标签或 sha256:... ID，不会拉取。')
    c['image']=required('镜像名称、地址或 ID',c.get('image',''),validator=image_reference)
    print('\n环境 ID：这套机器人部署的名字，例如 h5_test；不要与其他部署重名。')
    c['environment']=required('环境 ID',c.get('environment',''),validator=lambda v:pattern(v,r'[a-z][a-z0-9_-]{0,39}','使用小写字母开头的字母、数字、下划线或连字符，最长40字符'))
    suffix=c['environment']
    print('\nMongo URI 填写示例（把地址、端口、副本集名和认证信息换成实际值）：')
    print('  无认证：mongodb://10.0.0.10:27017/?replicaSet=rs0')
    print('  有认证：mongodb://benchmark:ENCODED_PASSWORD@10.0.0.10:27017/?replicaSet=rs0&authSource=admin')
    print('  多节点：mongodb://10.0.0.10:27017,10.0.0.11:27017/?replicaSet=rs0')
    print('  replicaSet 是副本集名；authSource 是账号所在的认证库，不一定是 admin。')
    print('  密码中的 @、:、/、?、# 等特殊字符需 URL 编码，例如 @ 写成 %40。')
    print('  填容器可达的地址，不填 localhost/127.0.0.1；直接粘贴完整 URI，不加引号。')
    c['mongo']=required('Mongo 副本集 URI',c.get('mongo',''),validator=mongo_uri)
    print('\nNATS：消息服务地址。无认证示例 nats://10.0.0.20:4222；有认证示例 nats://user:PASSWORD@10.0.0.20:4222。')
    c['nats']=required('NATS URL',c.get('nats',''),validator=nats_url)
    print('\netcd：配置服务地址。例如 http://10.0.0.30:2379；多个节点填 http://10.0.0.30:2379,http://10.0.0.31:2379。')
    print('必须包含主机和端口，不能只填 232 这样的主机尾号。')
    c['etcd']=required('etcd 地址',c.get('etcd',''),validator=etcd_endpoints)
    c['etcd']=','.join(x.strip() if '://' in x else 'http://'+x.strip() for x in c['etcd'].split(','))
    print('\nGate：游戏服的网关地址，例如 10.0.0.40:21001；不是管理台地址，也不能只写端口。')
    print('当前 Worker 启动要求此字段非空，所以仍需填写；Gate 暂不可达只提示，运行任务前必须可达。')
    c['gate']=required('Gate 地址 host:port',c.get('gate',''),validator=gate_address)
    print('\n默认区服 ID：整数，不是 IP 或端口。仅部署管理服务时可回车保留 1；实际任务目标服在管理台配置。')
    c['server']=required('默认区服 ID',c.get('server','1'),validator=lambda v:number(v,2147483647,'区服 ID'))
    print('\n业务库：保存机器人、计划和任务的 Mongo 库名，不是游戏玩家库。新环境可回车接受下面的专属库名。')
    c['database']=required('benchmark 业务库',c.get('database','gs_benchmark_'+suffix),validator=lambda v:pattern(v,r'[a-zA-Z][a-zA-Z0-9_-]{0,62}','库名以字母开头，例如 gs_benchmark_h5，不能只填 3'))
    print('\n配置库处理：首次部署输入 import（从镜像导入到新空库）；明确使用目标 Mongo 已有配置时输入 reuse（不改配置）。')
    print('直接填写英文 import 或 reuse，不是填写 1/2/3；回车接受下面显示的默认值。')
    c['config_mode']=required('配置库处理 import / reuse',c.get('config_mode','import'),validator=lambda v:choice(v,('import','reuse')))
    print('配置库名：import 填新的空库，reuse 填实际已有库；例如 gs_conf_benchmark_h5，与上面的业务库分开。')
    c['csv']=required('配置库名',c.get('csv','gs_conf_benchmark_'+suffix),validator=lambda v:config_database(v,c['database']))
    print('\netcd 配置前缀：本环境配置在 etcd 中的存放路径，不是 URL，也不是本机文件目录。')
    print('新环境通常直接回车接受下面按环境 ID 生成的路径；接已有环境才填写原路径，不要写数字 3。')
    c['root']=required('etcd 配置前缀',c.get('root','/benchmark/'+c['environment']+'/docker/runtime-config'),validator=etcd_root)
    print('\nWorker 版本稍后会连接 Mongo 读取并显示，再由你确认；现在不需要自行查数据库或猜版本。')
    c.setdefault('build','')
    print('\n环境加密密钥：新业务库可回车留空生成；已有业务库必须填原密钥，不能随便填数字。')
    c['secret']=required('环境加密密钥（已有库填原密钥；新库留空生成）',c.get('secret',''),
                         validator=environment_secret,optional=True)
    if c['secret']!=old.get('secret'):
        c['generated_secret']=False
    print('\n管理台认证：bypass 是免登录模式，可用于可信内网；已有 Portal 单点登录配置时填 portal。')
    c['auth']=required('管理台认证 bypass / portal',c.get('auth','bypass'),validator=lambda v:choice(v,('bypass','portal')))
    print('绑定 IP：127.0.0.1 仅本机访问；填写部署机内网 IP（例如 10.0.0.20）可供内网访问。')
    print('也可填 0.0.0.0 监听所有网卡，bypass 和 portal 均支持。浏览器使用实际 IP，不能用 0.0.0.0。')
    c['bind']=required('管理台绑定 IPv4',c.get('bind','127.0.0.1' if c['auth']=='bypass' else '0.0.0.0'),validator=ipaddress.IPv4Address)
    if c['auth']=='bypass' and not ipaddress.ip_address(c['bind']).is_loopback:
        print('你选择了免登录的网络访问方式，请确保管理台端口只允许可信内网访问。')
    print('管理台端口：一般回车使用 28082；若已占用，可填其他空闲端口，例如 29082。')
    c['port']=required('管理台宿主机端口',c.get('port','28082'),validator=lambda v:number(v,65535,'端口'))
    if c['auth']=='portal':
        for key,title in [('portal_url','Portal URL'),('portal_app','Portal App ID'),('portal_callback','Portal Callback URL')]:
            examples={'portal_url':'例如 https://portal.example.com，填写实际认证平台地址',
                      'portal_app':'填写该认证平台注册并分配的应用 ID，不是游戏区服 ID',
                      'portal_callback':'例如 https://robots.example.com/api/v1/auth/sso/callback，须与平台注册值一致'}
            print(examples[key])
            c[key]=required(title,c.get(key,''),validator=web_url if key!='portal_app' else None)
    # 已有部署以保存的实际资源名为准，不能因名称推导而换一套容器或数据卷。
    c['project']=old.get('project') or 'benchmark-'+c['environment']
    c['volume']=old.get('volume') or c['project']+'_worker-data'
    c['network']=old.get('network') or c['project']+'_default'
    c['worker']=old.get('worker') or 'worker-'+c['environment']+'-1'
    validate(c)
    return c


def make_snapshot(c):
    return {'schema_version':1,'revision':1,'fields':{
        'shared':{'mongo_uri':c['mongo'],'mongo_database':c['database'],'nats_url':c['nats'],
                  'event_topology_version':1,'event_shard_count':64,'jetstream_replicas':1},
        'manager':{'http_addr':':18082'},
        'worker':{'http_addr':':18083','gate_addr':c['gate'],'capacity':1000,'session_concurrency':100},
        'event_processor':{'http_addr':':18084','batch_size':128,'lease_ttl':'30s','renew_interval':'10s'},
        'runtime_log_processor':{'http_addr':':18085','batch_size':128,'detail_capacity':10000,'storage_mode':'mongo'}}}


def env_values(c):
    return {'COMPOSE_PROJECT_NAME':c['project'],'BENCHMARK_IMAGE':c['image'],
        'BENCHMARK_DBURL':c['mongo'],'BENCHMARK_DBNAME':c['database'],'BENCHMARK_CSV':c['csv'],
        'ROBOT_NATS_URL':c['nats'],'BENCHMARK_ETCD_ENDPOINTS':c['etcd'],
        'BENCHMARK_ETCD_RUNTIME_CONFIG_ROOT':c['root'],'BENCHMARK_GATEADDR':c['gate'],
        'BENCHMARK_SERVERID':c['server'],'ROBOT_PROCESS_ENVIRONMENT_ID':c['environment'],
        'ROBOT_WORKER_ID':c['worker'],'ROBOT_WORKER_BUILD_VERSION':c['build'],
        'BENCHMARK_ENVIRONMENT_SECRET_KEY':c['secret'],'WORKER_VOLUME':c['volume'],
        'DEPLOY_NETWORK':c['network'],
        'MANAGER_BIND_IP':c['bind'],'MANAGER_PORT':c['port'],
        'BENCHMARK_DEV_AUTH_BYPASS':str(c['auth']=='bypass').lower(),
        'BENCHMARK_BLOCK_TEST_ENABLED':str(bool(c.get('enable_block_test',False))).lower(),
        'BENCHMARK_BLOCK_TEST_ENVIRONMENTS':c['environment'] if c.get('enable_block_test') else 'test,local',
        'BENCHMARK_BLOCK_TEST_GM_ENVIRONMENTS':c['environment'] if c.get('enable_block_test') else 'test,local',
        'PORTAL_URL':c.get('portal_url',''),'PORTAL_APP_ID':c.get('portal_app',''),
        'PORTAL_CALLBACK_URL':c.get('portal_callback',''),
        'AUTH_COOKIE_SECURE':str(c.get('portal_callback','').startswith('https://')).lower()}


def write_assets(directory,c):
    if not c.get('preserve_snapshot'):
        c['snapshot']=make_snapshot(c)
    for name in ('docker-compose.yaml','deployment.env','deploy-settings.json','runtime-config.json'):
        p=directory/name
        if p.exists():
            private_write(directory/(name+'.previous'),p.read_text())
    compose=COMPOSE
    for service,values in c.get('upgrade_extra_environment',{}).items():
        match=re.search(r'^  '+re.escape(service)+r':\n.*?(?=^  [a-z]|^volumes:|\Z)',compose,re.M|re.S)
        if not match: continue
        block=match.group(0)
        reserved=set(re.findall(r'^      ([A-Z0-9_]+):',block,re.M))
        reserved.update(('TZ','BENCHMARK_ETCD_ENDPOINTS','BENCHMARK_ETCD_RUNTIME_CONFIG_ROOT'))
        extra=''.join('      '+key+': '+json.dumps(value.replace('$','$$'))+'\n'
                      for key,value in values.items() if key not in reserved)
        if not extra: continue
        if '    environment: *runtime-env\n' in block:
            replacement=block.replace('    environment: *runtime-env\n','    environment:\n      <<: *runtime-env\n'+extra,1)
        else:
            replacement=block.replace('      <<: *runtime-env\n','      <<: *runtime-env\n'+extra,1)
        compose=compose[:match.start()]+replacement+compose[match.end():]
    if c.get('worker_compose_model'):
        compose=json.dumps(c['worker_compose_model'],ensure_ascii=False,indent=2)+'\n'
    private_write(directory/'docker-compose.yaml',compose)
    # 单引号阻止 $ 插值；Compose 单引号内的单引号使用反斜杠转义。
    env=''.join(k+"='"+str(v).replace("'","\\'")+"'\n" for k,v in env_values(c).items())
    private_write(directory/'deployment.env',env)
    private_write(directory/'runtime-config.json',json.dumps(c['snapshot'],ensure_ascii=False,indent=2)+'\n')
    private_write(directory/'deploy-settings.json',json.dumps(c,ensure_ascii=False,indent=2)+'\n')


class Docker:
    def __init__(self, offline=False):
        if not shutil.which('docker'):
            raise DeployError('请先安装 Docker Engine 与 Compose v2')
        self.group=False
        if not offline and run(['docker','info'],check=False).returncode:
            if shutil.which('sg') and run(['sg','docker','-c','docker info'],check=False).returncode==0:
                self.group=True
            else:
                raise DeployError('无法访问 Docker。请启动 daemon 并让当前用户具有 docker 组权限')
        candidates=[['docker','compose']]
        if shutil.which('docker-compose'):
            candidates.append(['docker-compose'])
        for command in candidates:
            self.compose_command=command
            result=self.call(['compose','version','--short'],check=False)
            version=re.fullmatch(r'v?(\d+)\.\d+\.\d+[^\s]*',result.stdout.strip())
            if result.returncode==0 and version and int(version.group(1))>=2:
                print('Compose 命令：'+shlex.join(command)+'（'+result.stdout.strip()+'）')
                break
        else:
            raise DeployError('未找到可用的 Compose v2；支持 docker compose 或 docker-compose v2，不支持旧版 v1')

    def call(self,args,**kwargs):
        command=([*self.compose_command,*args[1:]] if args and args[0]=='compose'
                 else ['docker',*args])
        if self.group:
            command=['sg','docker','-c',shlex.join(command)]
        return run(command,**kwargs)

    def compose(self,directory,args,**kwargs):
        # 避免进程环境覆盖生成的 deployment.env；只清理本脚本管理的变量。
        with clean_environment():
            return self.call(['compose','--env-file',str(directory/'deployment.env'),
                              '-f',str(directory/'docker-compose.yaml'),*args],**kwargs)


@contextlib.contextmanager
def clean_environment():
    keys=set(re.findall(r'\$\{([A-Z_]+)',COMPOSE))|{'COMPOSE_FILE','COMPOSE_PROFILES','COMPOSE_PROJECT_NAME'}
    saved={k:os.environ.pop(k) for k in keys if k in os.environ}
    try: yield
    finally: os.environ.update(saved)


def helper(docker,c,action,quiet=False):
    result=docker.call(['run','--rm','--pull','never','-i','--network',c['network'],'--add-host','host.docker.internal:host-gateway',
        '--entrypoint','python3',c['image'],'-c',HELPER,action],
        data=json.dumps(c),timeout=1200 if action in ('import','replace_config') else 180,check=False)
    try:
        payload=json.loads(result.stdout)
    except ValueError as e:
        raise DeployError('镜像内检查程序无法运行，请确认组合镜像含 Python3/pymongo；容器未返回有效结果') from e
    if not payload.get('ok') or result.returncode:
        raise DeployError(payload.get('error','镜像内检查失败'))
    public={k:v for k,v in payload['result'].items() if k!='owner_secret_hash'}
    if not quiet: print(json.dumps(public,ensure_ascii=False),flush=True)
    return payload['result']


def pin_image(docker,c,local=False):
    if not local:
        result=docker.call(['pull',c['image']],timeout=1800,check=False,capture=False)
        if result.returncode:
            if not yes('拉取失败，是否现在交互登录镜像仓库后重试'):
                raise DeployError('镜像未拉取；检查标签、仓库权限和网络后重试')
            registry=c['image'].split('/')[0]
            docker.call(['login',registry],capture=False,timeout=600)
            docker.call(['pull',c['image']],capture=False,timeout=1800)
    image=json.loads(docker.call(['image','inspect',c['image']]).stdout)[0]
    repo=c['image'].split('@')[0]
    if ':' in repo.rsplit('/',1)[-1]: repo=repo.rsplit(':',1)[0]
    digest=next((x for x in image.get('RepoDigests',[]) if x.split('@')[0]==repo),None)
    if local: digest=image['Id']
    if not digest: raise DeployError('镜像缺少匹配仓库的 RepoDigest，无法固定内容')
    c['image']=digest
    c['image_build']=digest.split('sha256:')[-1][:12]
    print('已固定镜像：'+digest)


SERVICE_ROLES = {'benchmark':'manager','robot-worker':'robot_worker',
                 'robot-event-processor':'projection_processor',
                 'robot-runtime-log-processor':'runtime_log_processor'}


def container_env(container):
    return dict(x.split('=',1) for x in container['Config'].get('Env',[]) if '=' in x)


def normalized_endpoints(value):
    result=[]
    for item in value.split(','):
        address=item.strip()
        if address.startswith('http://'): address=address[len('http://'):]
        result.append(address.rstrip('/'))
    return sorted(result)


def find_local_deployment(docker,c):
    """按实际 etcd 入口寻找本机项目，兼容旧脚本的不同 Compose 项目名。"""
    ids=docker.call(['ps','-aq','--filter','label=com.docker.compose.project']).stdout.split()
    if not ids: return []
    groups={}
    for item in json.loads(docker.call(['inspect',*ids]).stdout):
        labels=item['Config'].get('Labels') or {}
        if str(labels.get('com.docker.compose.oneoff','')).lower()=='true': continue
        if labels.get('com.docker.compose.service') not in SERVICE_ROLES: continue
        env=container_env(item)
        matched=(env.get('BENCHMARK_ETCD_RUNTIME_CONFIG_ROOT')==c['root'] and
                 normalized_endpoints(env.get('BENCHMARK_ETCD_ENDPOINTS',''))==normalized_endpoints(c['etcd']))
        if not matched:
            if labels.get('com.docker.compose.project')==c['project']:
                raise DeployError('同名本机项目属于另一套 etcd 配置，未接管')
            continue
        groups.setdefault(labels['com.docker.compose.project'],[]).append(item)
    if len(groups)>1:
        raise DeployError('同一 etcd 前缀匹配多个本机项目，需先处理重复部署：'+', '.join(groups))
    if not groups: return []
    containers=next(iter(groups.values()))
    services=[x['Config']['Labels']['com.docker.compose.service'] for x in containers]
    if len(services)!=4 or set(services)!=set(SERVICE_ROLES):
        raise DeployError('本机旧项目没有唯一的四个服务容器，无法自动建立可靠回退；请先核对旧部署')
    return containers


def rollback_model(docker,containers):
    """冻结原 Compose，并以实际容器值覆盖可变镜像、环境、端口和挂载。"""
    manager=next(x for x in containers if x['Config']['Labels']['com.docker.compose.service']=='benchmark')
    labels=manager['Config']['Labels'];project=labels['com.docker.compose.project']
    files=labels.get('com.docker.compose.project.config_files','').split(',')
    if not files or any(not Path(x).is_file() for x in files):
        raise DeployError('旧 Compose 文件在本机不可读，无法生成回退配置；请恢复旧文件后更新')
    args=['compose','-p',project]
    workdir=labels.get('com.docker.compose.project.working_dir')
    if workdir: args+=['--project-directory',workdir]
    for f in files: args+=['-f',f]
    for f in filter(None,labels.get('com.docker.compose.project.environment_file','').split(',')):
        if not Path(f).is_file(): raise DeployError('旧 env 文件不可读，无法生成回退配置')
        args+=['--env-file',f]
    with clean_environment():
        model=json.loads(docker.call(args+['config','--format','json']).stdout)
    model['services']={k:v for k,v in model['services'].items() if k in SERVICE_ROLES}
    for item in containers:
        name=item['Config']['Labels']['com.docker.compose.service'];service=model['services'][name]
        if any(k not in SERVICE_ROLES for k in service.get('depends_on',{})):
            raise DeployError('旧 Compose 依赖其他服务，不能自动裁剪为四服务回退配置')
        service['image']=item['Image'];service['pull_policy']='never'
        service['container_name']=item['Name'].lstrip('/')
        service['environment']={k:v.replace('$','$$') for k,v in container_env(item).items()}
        service.pop('env_file',None)
        ports=[]
        for target,bindings in (item['HostConfig'].get('PortBindings') or {}).items():
            port,protocol=target.split('/')
            for binding in bindings or []:
                if not binding['HostPort'] or binding['HostPort']=='0':
                    raise DeployError('旧部署使用动态宿主端口，不能保证原地址回退')
                entry={'target':int(port),'published':binding['HostPort'],'protocol':protocol}
                if binding.get('HostIp'): entry['host_ip']=binding['HostIp']
                ports.append(entry)
        if ports: service['ports']=ports
        else: service.pop('ports',None)
        volumes=[]
        for mount in item.get('Mounts',[]):
            if mount['Type'] not in ('bind','volume'):
                raise DeployError('旧部署包含无法自动还原的挂载类型：'+mount['Type'])
            source=mount.get('Name') if mount['Type']=='volume' else mount['Source']
            volumes.append({'type':mount['Type'],'source':source,'target':mount['Destination'],'read_only':not mount['RW']})
            if mount['Type']=='volume':model.setdefault('volumes',{})[source]={'external':True,'name':source}
        service['volumes']=volumes
    for kind in ('networks','volumes'):
        for name,config in list(model.get(kind,{}).items()):
            actual=(config or {}).get('name') or project+'_'+name
            model[kind][name]={'external':True,'name':actual}
    return model


def local_registrations(docker,c,containers):
    records=helper(docker,c,'instances',quiet=True)['instances']
    owned=[]
    for record in records:
        matches=[]
        for item in containers:
            if not item['State']['Running']: continue
            role=SERVICE_ROLES[item['Config']['Labels']['com.docker.compose.service']]
            addresses={v['IPAddress'] for v in item['NetworkSettings']['Networks'].values()}
            if record['role']==role and record.get('address','').rsplit(':',1)[0] in addresses:
                matches.append(item)
        if len(matches)!=1:
            raise DeployError('etcd 中仍有无法归属本机的实例：'+record['role']+' '+record.get('address','')+'；不会停止其他机器的服务')
        owned.append(record['instance_id'])
    return owned


def wait_no_instances(docker,c):
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        records=helper(docker,c,'instances',quiet=True)['instances']
        if all(x['instance_id'] in c.get('retained_instances',[]) for x in records): return
        print('等待旧实例租约释放……',flush=True)
        time.sleep(3)
    raise DeployError('旧实例未在90秒内全部退出；未删除注册键，不启动第二套 Manager')


def wait_restored(docker,project,originals):
    expected={x['Config']['Labels']['com.docker.compose.service']:x for x in originals}
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        ids=docker.call(['ps','-aq','--filter','label=com.docker.compose.project='+project]).stdout.split()
        actual={}
        if ids:
            for item in json.loads(docker.call(['inspect',*ids]).stdout):
                labels=item['Config'].get('Labels') or {}
                if str(labels.get('com.docker.compose.oneoff','')).lower()!='true':
                    actual[labels.get('com.docker.compose.service')]=item
        def restored(name,old):
            new=actual.get(name)
            if not new or new['Image']!=old['Image'] or new['State']['Running']!=old['State']['Running']: return False
            if old['State'].get('Health',{}).get('Status')=='healthy':
                return new['State'].get('Health',{}).get('Status')=='healthy'
            return True
        if all(restored(name,old) for name,old in expected.items()): return
        time.sleep(3)
    raise DeployError('旧容器已恢复配置但未恢复原启动/健康状态，请查看旧版本日志')


def upgrade_deployment(docker,directory,c,containers,worker_only=False):
    services={x['Config']['Labels']['com.docker.compose.service']:x for x in containers}
    manager,worker=services['benchmark'],services['robot-worker']
    menv,wenv=container_env(manager),container_env(worker)
    if wenv.get('ROBOT_PROCESS_ENVIRONMENT_ID')!=c['environment']:
        raise DeployError('旧 Worker 的环境 ID 与本次不同；环境迁移不能作为普通镜像更新处理')
    secret=wenv.get('BENCHMARK_ENVIRONMENT_SECRET_KEY') or menv.get('BENCHMARK_ENVIRONMENT_SECRET_KEY')
    if not secret or (c['secret'] and c['secret']!=secret):
        raise DeployError('无法复用旧容器的环境密钥，或你填写的密钥不同，未停止旧服务')
    mounts=[x for x in worker['Mounts'] if x['Destination']==wenv.get('ROBOT_WORKER_DATA_DIR','/var/lib/robot-worker')]
    if len(mounts)!=1 or mounts[0]['Type']!='volume':
        raise DeployError('旧 Worker 不是受支持的命名卷部署，不能自动替换持久化目录')
    networks=set(manager['NetworkSettings']['Networks'])
    for item in containers: networks &= set(item['NetworkSettings']['Networks'])
    if not networks: raise DeployError('旧四服务没有共同 Docker 网络，不能直接更新')
    project=manager['Config']['Labels']['com.docker.compose.project']
    c.update(project=project,secret=secret,generated_secret=False,volume=mounts[0]['Name'],
             worker=wenv['ROBOT_WORKER_ID'],network=c['network'] if c['network'] in networks else sorted(networks)[0])
    c['upgrade_extra_environment']={name:{key:value for key,value in container_env(item).items()
        if key.startswith(('BENCHMARK_','ROBOT_','PORTAL_','AUTH_','WEBAUTH_'))}
        for name,item in services.items()}
    state=helper(docker,c,'upgrade_state',quiet=True)
    actual=state['snapshot'];shared=actual['fields']['shared']
    if shared['mongo_uri']!=c['mongo'] or shared['mongo_database']!=c['database']:
        raise DeployError('本次 Mongo 连接或业务库与旧环境不同；数据库迁移不能与普通镜像更新混用')
    differences=[]
    desired=make_snapshot(c)
    for section,fields in desired['fields'].items():
        for key,value in fields.items():
            previous=actual['fields'].get(section,{}).get(key)
            if previous!=value: differences.append((section+'.'+key,previous,value))
    if differences:
        print('发现共享配置差异：')
        for name,before,after in differences:
            def display(value):
                if name.endswith(('mongo_uri','nats_url')) and isinstance(value,str):
                    u=urlsplit(value)
                    return u.scheme+'://'+str(u.hostname)+(':'+str(u.port) if u.port else '')+('（认证信息已隐藏）' if u.username or u.password else '')
                return str(value)
            print('  '+name+'：旧值 '+display(before)+' → 本次填写 '+display(after))
        print('普通更新将复用旧共享配置；切换 NATS、数据库或数据迁移需要单独安排，不会覆盖旧 revision。')
        if not yes('是否沿用旧共享配置继续更新程序'): raise DeployError('已取消，旧服务未停止')
    c['nats']=shared['nats_url'];c['gate']=actual['fields']['worker']['gate_addr']
    c['snapshot']=actual;c['preserve_snapshot']=True
    for role,port in [('manager',18082),('worker',18083),('event_processor',18084),('runtime_log_processor',18085)]:
        if actual['fields'][role]['http_addr']!=':'+str(port):
            raise DeployError('旧监听端口不符合当前模板，请先明确端口迁移方案：'+role)
    c['own_instances']=local_registrations(docker,c,containers)
    original_model=rollback_model(docker,containers)
    current_csv=menv.get('BENCHMARK_CSV') or wenv.get('ROBOT_CSV_DATABASE')
    replace_config=False
    c.pop('replace_config_database',None)
    print(f'\n检测到本机旧项目 {project}，将保留原密钥、Worker ID 和数据卷 {c["volume"]}。')
    if worker_only:
        print('仅更新 Worker：复用配置库 '+str(current_csv)+'、共享配置及各容器配置。')
    else:
        print('1：停服后用新镜像覆盖原配置库 '+str(current_csv)+'（默认；不保留旧配置数据）')
        print('2：复用原配置库，不更新配置（仅适合配置未变化）')
        mode=required('升级配置库请选择 1 或 2','1',validator=lambda v:choice(v,('1','2')))
        replace_config=mode=='1'
    c['csv']=current_csv;c['config_mode']='reuse'
    restore_config=dict(c,image=worker['Image'])
    if replace_config:
        config_database(current_csv,c['database'])
        if menv.get('BENCHMARK_CSV')!=wenv.get('ROBOT_CSV_DATABASE'):
            raise DeployError('Manager 与 Worker 配置库不同，不能自动覆盖')
        c['replace_config_database']=current_csv
        restore_config['replace_config_database']=current_csv
        helper(docker,c,'config_source',quiet=True)
        helper(docker,restore_config,'config_source',quiet=True)
        print('将清空并重导 '+current_csv+'；该库必须为本部署专用，不能被游戏服或其他部署共用。')
        print('回退时从旧 Worker 镜像重导配置；旧库手动修改的数据不会保留。')
    c['build']=required('新 Worker 版本（回车使用镜像摘要）',c['image_build'])
    c['upgrade_manifest_ejson']=state['manifest_ejson'];c['upgrade_token']=secrets.token_hex(16)
    targets=[worker] if worker_only else containers
    retained=[item for item in containers if item not in targets]
    if worker_only:
        if not all(item['State']['Running'] for item in retained):
            raise DeployError('仅更新 Worker 要求其余三个服务正在运行；请先恢复原服务')
        records=helper(docker,c,'instances',quiet=True)['instances']
        c['retained_instances']=[item['instance_id'] for item in records
            if item['instance_id'] in c['own_instances'] and item['role']!='robot_worker']
        if len(c['retained_instances'])!=3:
            raise DeployError('其余三个服务的注册信息不完整，未停止 Worker')
        model=json.loads(json.dumps(original_model))
        model['services']['robot-worker']['image']=c['image']
        model['services']['robot-worker']['environment']['ROBOT_WORKER_BUILD_VERSION']=c['build'].replace('$','$$')
        c['worker_compose_model']=model
    validate(c)
    print('旧 Worker 版本：'+state['build_version']+' → 新版本：'+c['build'])
    print('更新容器：'+', '.join(x['Name'].lstrip('/') for x in targets))
    print('这次只处理兼容声明为协议1/状态机1的更新；不执行业务数据格式迁移。')
    print('确认后会自动停止旧容器、更新 manifest、启动并验收；不需要你手动重启。')
    question='确认配置库为本部署专用，并覆盖配置更新四服务' if replace_config else '确认更新本机这套部署'
    if not yes(question): print('已取消，旧容器未停止。');return
    backup=directory/('backup-upgrade-'+time.strftime('%Y%m%d-%H%M%S')+'-'+c['upgrade_token'][:6])
    backup.mkdir(mode=0o700)
    files=('docker-compose.yaml','deployment.env','deploy-settings.json','runtime-config.json','answers.json','health-result.json')
    existed=[]
    for name in files:
        if (directory/name).exists():
            private_write(backup/name,(directory/name).read_text());existed.append(name)
    private_write(backup/'old-compose.json',json.dumps(original_model,ensure_ascii=False,indent=2))
    private_write(backup/'remote-state.json',json.dumps(state,ensure_ascii=False,indent=2))
    private_write(backup/'rollback-context.json',json.dumps(c,ensure_ascii=False,indent=2))
    if replace_config:
        restore_config['own_instances']=[]
        private_write(backup/'config-rollback-context.json',json.dumps(restore_config,ensure_ascii=False,indent=2))
    with tempfile.TemporaryDirectory(prefix='prepare-',dir=directory) as tmp:
        stage=Path(tmp);write_assets(stage,c)
        docker.compose(stage,['--profile','init','config','--quiet'])
        if not worker_only:
            report=json.loads(docker.compose(stage,['run','--rm','robot-jetstream-provision','check']).stdout)
            if not report.get('ok'): raise DeployError('旧 NATS Stream 未就绪，旧服务未停止')
    if not worker_only and not replace_config: helper(docker,c,'import')
    started=[x['Id'] for x in targets if x['State']['Running']]
    journal={'phase':'prepared','scope':'worker' if worker_only else 'all','project':project,
             'backup':str(backup),'originally_running':started,'files':existed}
    private_write(backup/'journal.json',json.dumps(journal,indent=2))
    mutation_attempted=False
    config_attempted=False
    try:
        journal['phase']='stopping';private_write(backup/'journal.json',json.dumps(journal,indent=2))
        if started: docker.call(['stop','--time','60',*started],timeout=240,capture=False)
        wait_no_instances(docker,c)
        c['own_instances']=c.get('retained_instances',[])
        fresh=helper(docker,c,'upgrade_state',quiet=True)
        if fresh!=state: raise DeployError('停止期间共享配置或 manifest 发生变化，取消切换')
        if replace_config:
            journal['phase']='replacing_config';private_write(backup/'journal.json',json.dumps(journal,indent=2))
            config_attempted=True
            helper(docker,c,'replace_config')
        mutation_attempted=True
        helper(docker,c,'upgrade_manifest')
        write_assets(directory,c)
        private_write(directory/'answers.json',json.dumps(c,ensure_ascii=False,indent=2))
        journal['phase']='starting';private_write(backup/'journal.json',json.dumps(journal,indent=2))
        up=['up','-d','--pull','never']
        if worker_only: up+=['--no-deps','robot-worker']
        docker.compose(directory,up,timeout=180,capture=False)
        health=verify_worker(docker,directory,c,retained) if worker_only else verify(docker,directory,c)
        journal['phase']='complete';private_write(backup/'journal.json',json.dumps(journal,indent=2))
        print('基础服务更新验收通过（镜像、进程健康、注册租约）。回退备份：'+str(backup))
        print('镜像：'+c['image']+'；管理台端口：'+c['port'])
        if worker_only:
            print('Worker 更新完成，其余三个容器未重建或重启；请通过单机器人任务验证游戏协议。')
        else:
            report_business_readiness(c,health)
    except BaseException as original_error:
        print('更新失败，正在恢复旧版本……',flush=True)
        try:
            # 只操作刚才明确匹配的项目，绝不停止其他项目。
            ids=docker.call(['ps','-aq','--filter','label=com.docker.compose.project='+project]).stdout.split()
            relevant=[]
            if ids:
                for item in json.loads(docker.call(['inspect',*ids]).stdout):
                    labels=item['Config'].get('Labels') or {}
                    selected={'robot-worker'} if worker_only else SERVICE_ROLES
                    if labels.get('com.docker.compose.service') in selected and str(labels.get('com.docker.compose.oneoff','')).lower()!='true': relevant.append(item['Id'])
            if relevant: docker.call(['stop','--time','60',*relevant],timeout=240)
            wait_no_instances(docker,c)
            c['own_instances']=c.get('retained_instances',[])
            if config_attempted:
                restore_config['own_instances']=[]
                helper(docker,restore_config,'replace_config')
            if mutation_attempted: helper(docker,c,'restore_manifest')
            for name in files:
                if name in existed: private_write(directory/name,(backup/name).read_text())
                elif (directory/name).exists(): (directory/name).unlink()
            if relevant: docker.call(['rm',*relevant])
            args=['compose','-p',project,'-f',str(backup/'old-compose.json')]
            with clean_environment():
                restore=['up','--no-start','--pull','never']
                if worker_only: restore+=['--no-deps','robot-worker']
                docker.call(args+restore,timeout=180)
                active_services=[x['Config']['Labels']['com.docker.compose.service'] for x in targets if x['Id'] in started]
                if active_services: docker.call(args+['start',*active_services],timeout=180,capture=False)
            wait_restored(docker,project,targets)
            if worker_only: verify_retained(docker,retained)
            journal['phase']='rolled_back';private_write(backup/'journal.json',json.dumps(journal,indent=2))
            print('旧镜像、manifest、部署文件和原有启动状态已恢复。'+
                  ('原配置库已从旧镜像重新导入。' if config_attempted else '配置库未改写。'))
        except BaseException as rollback_error:
            journal['phase']='rollback_failed';private_write(backup/'journal.json',json.dumps(journal,indent=2))
            raise DeployError('自动回退未完成，请保留现场并查看 '+str(backup)+'；'+str(rollback_error)) from original_error
        raise DeployError('本次更新失败，已回退；'+str(original_error)) from original_error


def select_worker_build(docker,c):
    info=helper(docker,c,'manifest_info',quiet=True)
    record=info['manifest']
    print(f"\n已查询业务库 {c['database']}，环境 {c['environment']} 的 Worker 兼容记录。")
    if record:
        version=record.get('build_version')
        if not isinstance(version,str) or not version.strip():
            raise DeployError('已有 manifest 缺少有效 build_version，请先检查该记录')
        print('数据库已有版本：'+version)
        print('记录位置：bm_robot_worker_manifests，environment_id='+c['environment'])
        if c.get('build') and c['build']!=version:
            print('你之前保存的版本是 '+c['build']+'，与数据库不同，请在下面重新选择。')
        print('1：沿用已有兼容版本 '+version+'（仅适用于与原环境兼容的程序，不修改数据库版本记录）')
        print('2：取消本次部署，先核对升级兼容性或准备独立的新环境')
        print('沿用这个版本标识并不证明新镜像兼容；不要用它跳过实际的协议或数据兼容核对。')
        action=required('请选择 1 或 2（必须明确输入）',validator=lambda v:choice(v,('1','2')))
        if action=='2':
            raise DeployError('已取消；未覆盖已有 manifest。升级需要先确认兼容性，再安排旧 Worker 停止和版本记录更新')
        c['build']=version
    else:
        default=c.get('build') or c['image_build']
        print('该环境还没有 manifest；新版本默认取镜像摘要，也可以填写你自己的版本标识。')
        c['build']=required('新 Worker build_version（回车接受显示值）',default)


def own_instances(docker,c):
    """只允许重启本目录对应环境的现有项目，不能接管另一套部署。"""
    ids=docker.call(['ps','-aq','--filter','label=com.docker.compose.project='+c['project']]).stdout.split()
    if not ids:
        return []
    containers=json.loads(docker.call(['inspect',*ids]).stdout)
    for item in containers:
        env=dict(x.split('=',1) for x in item['Config'].get('Env',[]) if '=' in x)
        if env.get('BENCHMARK_ETCD_RUNTIME_CONFIG_ROOT')!=c['root'] or normalized_endpoints(env.get('BENCHMARK_ETCD_ENDPOINTS',''))!=normalized_endpoints(c['etcd']):
            raise DeployError('相同 Compose 项目名已被另一套环境使用，请换环境 ID')
    manager=next((x for x in containers if x['Config'].get('Labels',{}).get('com.docker.compose.service')=='benchmark'
                  and x['State']['Running']),None)
    if not manager:
        return []
    response=docker.call(['exec',manager['Id'],'curl','--fail','--silent','--max-time','5',
                          'http://127.0.0.1:18082/api/robot-manager/runtime-health'],check=False)
    if c['auth']=='portal':
        instances=helper(docker,c,'instances',quiet=True)['instances']
    else:
        try:
            instances=json.loads(response.stdout)['data']['instances']
        except (ValueError,KeyError) as e:
            raise DeployError('现有 Manager 状态不可读，先检查已有部署再重试') from e
    addresses={network['IPAddress'] for x in containers for network in x['NetworkSettings']['Networks'].values()}
    return [x['instance_id'] for x in instances if x.get('address','').rsplit(':',1)[0] in addresses]


def report_business_readiness(c,health):
    status=next((x for x in health.get('execution_readiness',[]) if x.get('environment_id')==c['environment']),None)
    if not status or status.get('ready') is not True:
        reason=status.get('reason','unknown') if status else 'not_observed'
        print('业务尚未验收通过：环境 '+c['environment']+' 暂不能确认可投放，原因：'+reason)
        if status and status.get('operator_hint'): print(status['operator_hint'])
        print('请检查管理台环境级就绪状态；基础服务更新成功不等于机器人任务可以启动。')
        return
    print('业务环境 '+c['environment']+' 已就绪；健康 Worker：'+str(status.get('healthy_workers',0))+
          '，可用槽位：'+str(status.get('available_slots',0)))


def verify_retained(docker,originals):
    """按容器 ID 和启动时间确认未更新的服务没有被重建或重启。"""
    actual=json.loads(docker.call(['inspect',*[x['Id'] for x in originals]]).stdout)
    by_id={item['Id']:item for item in actual}
    for old in originals:
        new=by_id.get(old['Id'])
        if (not new or new['Image']!=old['Image'] or not new['State']['Running']
                or new['State']['StartedAt']!=old['State']['StartedAt']):
            raise DeployError('未更新服务的运行状态发生变化：'+old['Name'])


def verify_worker(docker,directory,c,retained):
    expected=json.loads(docker.call(['image','inspect',c['image']]).stdout)[0]['Id']
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        verify_retained(docker,retained)
        ids=docker.compose(directory,['ps','-q','robot-worker']).stdout.split()
        if len(ids)==1:
            item=json.loads(docker.call(['inspect',ids[0]]).stdout)[0]
            env=container_env(item)
            data=helper(docker,c,'instances',quiet=True)
            addresses={v['IPAddress'] for v in item['NetworkSettings']['Networks'].values()}
            workers=[r for r in data['instances'] if r['role']=='robot_worker']
            registered=(len(workers)==1 and workers[0].get('worker_id')==c['worker']
                and workers[0].get('build_version')==c['build']
                and workers[0].get('address','').rsplit(':',1)[0] in addresses
                and workers[0].get('lease_status')=='fresh'
                and workers[0].get('config_status')=='aligned')
            if (item['Image']==expected and env.get('ROBOT_WORKER_BUILD_VERSION')==c['build']
                    and item['State'].get('Health',{}).get('Status')=='healthy' and registered):
                ready=docker.call(['exec',item['Id'],'curl','--fail','--silent','--max-time','5',
                    '-o','/dev/null','http://127.0.0.1:18083/readyz'],check=False)
                if ready.returncode==0:
                    data['worker_image_id']=expected
                    data['retained_container_ids']=[x['Id'] for x in retained]
                    private_write(directory/'health-result.json',json.dumps(data,ensure_ascii=False,indent=2)+'\n')
                    return data
        print('等待新 Worker 镜像、版本、健康与租约就绪（其余三个服务保持运行）……',flush=True)
        time.sleep(5)
    raise DeployError('新 Worker 在180秒内未通过镜像、版本和就绪验收')


def verify(docker,directory,c):
    roles={'manager','projection_processor','robot_worker','runtime_log_processor'}
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        ids=docker.compose(directory,['ps','-q']).stdout.split()
        if len(ids)==4:
            containers=json.loads(docker.call(['inspect',*ids]).stdout)
            healthy=all(x['State'].get('Health',{}).get('Status')=='healthy' for x in containers)
            try:
                if c['auth']=='portal':
                    data=helper(docker,c,'instances',quiet=True)
                    data['execution_readiness']=[{'environment_id':c['environment'],'ready':None,
                        'reason':'login_required','operator_hint':'请登录管理台查看环境级就绪状态'}]
                else:
                    health=docker.compose(directory,['exec','-T','benchmark','curl','--fail','--silent',
                        '--max-time','5','http://127.0.0.1:18082/api/robot-manager/runtime-health'],check=False)
                    data=json.loads(health.stdout)['data']
                fresh={i['role'] for i in data['instances'] if i.get('lease_status')=='fresh'
                       and i.get('config_status')=='aligned'}
                if healthy and roles <= fresh:
                    page=docker.compose(directory,['exec','-T','benchmark','curl','--fail','--silent',
                        '--max-time','5','-o','/dev/null','http://127.0.0.1:18082/ui/'],check=False)
                    if page.returncode==0:
                        private_write(directory/'health-result.json',json.dumps(data,ensure_ascii=False,indent=2)+'\n')
                        return data
            except (ValueError,KeyError,TypeError):
                pass
        print('等待四服务健康与租约就绪……',flush=True)
        time.sleep(5)
    raise DeployError('180 秒内未通过验收；容器已保留，请用生成的 Compose 执行 ps / logs 排查')


def control_deployment(docker,directory,c,action):
    containers=find_local_deployment(docker,c)
    if not containers:
        raise DeployError('未找到已有四服务容器；请先完成部署，启动操作不会创建容器')
    for item in containers:
        if item['Config']['Labels']['com.docker.compose.project']!=c['project']:
            raise DeployError('部署目录与实际容器项目名不同，未执行启停')
    ids=docker.compose(directory,['ps','-aq',*SERVICE_ROLES]).stdout.split()
    if set(ids)!={item['Id'] for item in containers}:
        raise DeployError('Compose 与已识别容器不一致，未执行启停')
    services={item['Config']['Labels']['com.docker.compose.service']:item for item in containers}
    if action=='stop' and not any(item['State']['Running'] for item in containers):
        print('四个服务已停止，容器和数据均保留。')
        return
    # 使用实际 Worker 镜像做只读检查，避免配置中的镜像标签已漂移。
    runtime=dict(c)
    runtime['image']=services['robot-worker']['Image']
    runtime['build']=container_env(services['robot-worker']).get('ROBOT_WORKER_BUILD_VERSION','')
    runtime['own_instances']=local_registrations(docker,runtime,containers)
    helper(docker,runtime,action+'_preflight')
    if action=='stop':
        # 先关闭调度入口，再关闭 Worker，最后关闭事件处理器。
        for service in SERVICE_ROLES:
            item=services[service]
            if item['State']['Running']:
                docker.call(['stop','--time','60',item['Id']],timeout=90,capture=False)
        stopped=json.loads(docker.call(['inspect',*ids]).stdout)
        if any(item['State']['Running'] for item in stopped):
            raise DeployError('部分服务仍在运行，请检查容器状态后重试')
        runtime['retained_instances']=[]
        wait_no_instances(docker,runtime)
        print('四个服务已停止；容器、镜像、配置和数据卷均保留。')
    else:
        inactive=[item['Id'] for item in containers if not item['State']['Running']]
        if inactive: docker.call(['start',*inactive],timeout=180,capture=False)
        health=verify(docker,directory,runtime)
        print('四个服务已启动并通过基础健康验收；未拉取镜像或修改部署配置。')
        report_business_readiness(c,health)


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dir',help='部署文件保存目录，重复运行可复用参数')
    upgrades=parser.add_mutually_exclusive_group()
    upgrades.add_argument('--upgrade',action='store_true',help='整体更新本机四服务，失败回退')
    upgrades.add_argument('--upgrade-worker',action='store_true',help='仅更新本机 Worker，复用配置库，其余三个服务保持运行，失败仅回退 Worker')
    parser.add_argument('--local-image',action='store_true',help='只使用本机已有镜像，跳过 pull/login')
    parser.add_argument('--non-interactive',action='store_true',help='仅使用已有部署答案文件中的默认值；缺项即停止')
    parser.add_argument('--yes',action='store_true',help='只与 --non-interactive 联用，确认首次部署；升级/登录等其他确认仍拒绝')
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare-only',action='store_true',help='仅生成文件，不拉镜像、不访问依赖、不启动服务')
    modes.add_argument('--check',action='store_true',help='读取已有参数并只读检查依赖；镜像须已拉取')
    modes.add_argument('--stop',action='store_true',help='检查任务和会话已排空后关闭已有四服务，保留容器和数据')
    modes.add_argument('--start',action='store_true',help='启动已有四服务并验收，不拉镜像、不重新填写配置')
    args=parser.parse_args()
    global AUTO_DEFAULTS, AUTO_CONFIRM
    AUTO_DEFAULTS=args.non_interactive
    AUTO_CONFIRM=args.yes
    if args.yes and not args.non_interactive:
        parser.error('--yes 只允许与 --non-interactive 联用')
    lifecycle=args.start or args.stop
    if (args.upgrade or args.upgrade_worker) and (args.check or args.prepare_only or lifecycle):
        parser.error('--upgrade / --upgrade-worker 不能与 --check、--prepare-only、--start 或 --stop 同时使用')
    if lifecycle and args.local_image:
        parser.error('--start / --stop 不切换镜像，不能与 --local-image 同时使用')
    os.umask(0o077)
    if not args.check and not lifecycle and not args.non_interactive and not sys.stdin.isatty():
        raise DeployError('请在交互终端运行；非交互只读检查使用 --check --dir PATH')
    default_directory=str(Path.cwd()/'config')
    directory=Path(args.dir or (default_directory if lifecycle else required('部署文件保存目录',default_directory))).expanduser().resolve()
    if lifecycle:
        for name in ('deploy-settings.json','deployment.env','docker-compose.yaml'):
            if not (directory/name).is_file():
                raise DeployError('启停需要已有部署文件：'+str(directory/name)+'；请用 --dir 指定原部署目录')
    if args.check and not (directory/'deploy-settings.json').exists():
        raise DeployError('--check 需要已有部署目录中的 deploy-settings.json')
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.deploy.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e: raise DeployError('同目录另一个部署正在执行') from e
        saved=directory/'deploy-settings.json'
        answers=directory/'answers.json'
        old=json.loads(saved.read_text()) if saved.exists() else json.loads(answers.read_text()) if answers.exists() else {}
        if lifecycle:
            validate(old)
            control_deployment(Docker(),directory,old,'start' if args.start else 'stop')
            return
        if not old and any((directory/n).exists() for n in ('docker-compose.yaml','deployment.env')):
            raise DeployError('目录已有非本脚本管理的部署文件；请换空目录，避免覆盖')
        if args.upgrade_worker:
            if not saved.exists(): raise DeployError('--upgrade-worker 需要已有部署目录中的 deploy-settings.json')
            c=dict(old)
            print('仅更新 Worker：复用已有部署参数。请确认新镜像与现有内部事件协议、存档和配置兼容。')
            c['image']=required('新 Worker 镜像名称、地址或 ID',c.get('image',''),validator=image_reference)
        else:
            c=old if args.check else collect(old)
        if not args.check:
            c.pop('worker_compose_model',None)
            c.pop('retained_instances',None)
        validate(c)
        if not args.check:
            private_write(answers,json.dumps(c,ensure_ascii=False,indent=2)+'\n')
        docker=Docker(offline=args.prepare_only)
        if args.check:
            if not c.get('preserve_snapshot'): c['snapshot']=make_snapshot(c)
            c['own_instances']=own_instances(docker,c)
            docker.call(['network','inspect',c['network']])
            helper(docker,c,'probe')
            print('只读检查完成，未修改数据库、etcd 或运行服务。')
            return
        if args.prepare_only:
            c['build']=c['build'] or 'prepare-only'
            if not c['secret']:
                c['secret']=base64.b64encode(secrets.token_bytes(32)).decode()
                c['generated_secret']=True
            c['prepared_only']=True
            write_assets(directory,c)
            docker.compose(directory,['--profile','init','config','--quiet'])
            print('已生成并校验配置：'+str(directory)+'；尚未部署，实际执行前仍需依赖检查。')
            return
        if c.pop('prepared_only',False) and c['build']=='prepare-only': c['build']=''
        pin_image(docker,c,local=args.local_image)
        local=find_local_deployment(docker,c)
        if local:
            upgrade_deployment(docker,directory,c,local,worker_only=args.upgrade_worker)
            return
        if args.upgrade or args.upgrade_worker:
            raise DeployError('未找到匹配该 etcd 入口的本机旧部署；不会接管其他机器。首次部署请不加 --upgrade')
        c['snapshot']=make_snapshot(c)
        c['own_instances']=own_instances(docker,c)
        networks=docker.call(['network','ls','--format','{{.Name}}']).stdout.splitlines()
        if c['network'] not in networks:
            docker.call(['network','create','--label','benchmark.deploy.project='+c['project'],c['network']])
        select_worker_build(docker,c)
        private_write(answers,json.dumps(c,ensure_ascii=False,indent=2)+'\n')
        print('检查容器到 Mongo、etcd、NATS、Gate 的连接及已有数据……',flush=True)
        probe=helper(docker,c,'probe')
        if not probe['gate_reachable']:
            print('提示：Gate 当前不可达；可以部署管理服务，运行机器人任务前必须恢复 Gate。',flush=True)
        known_secret=probe.get('owner_secret_hash')==hashlib.sha256(c['secret'].encode()).hexdigest()
        if probe['business_collections'] and (not c['secret'] or (c.get('generated_secret') and not known_secret)):
            c['secret']=required('已有业务库必须提供原环境加密密钥',validator=environment_secret)
            c['generated_secret']=False
        if not c['secret']:
            c['secret']=base64.b64encode(secrets.token_bytes(32)).decode()
            c['generated_secret']=True
        validate(c)
        # 身份参数变化不覆盖原部署，防止同目录变成另一个项目。
        for key in ('project','mongo','database','environment','root','volume','secret'):
            if saved.exists() and not old.get('prepared_only') and old.get(key)!=c.get(key):
                raise DeployError('已有部署身份参数 '+key+' 改变；请使用新目录，不覆盖原部署')
        print(f"部署项目：{c['project']}；业务库：{c['database']}；配置库：{c['csv']}（{c['config_mode']}）")
        print(f"将初始化专属资源并启动四个服务；管理台绑定 {c['bind']}:{c['port']}。")
        if not yes('确认执行上述部署'):
            print('已取消，未初始化数据库或 etcd。'); return
        write_assets(directory,c)
        docker.compose(directory,['--profile','init','config','--quiet'])
        # 不占用其他服务的端口，也不自动停止既有容器。
        existing=docker.compose(directory,['ps','-q','benchmark']).stdout.strip()
        if not existing:
            with socket.socket() as sock:
                try: sock.bind((c['bind'],int(c['port'])))
                except OSError as e: raise DeployError('管理台地址无法绑定或端口已占用，请换端口') from e
        # Compose v2 会先检查项目的外部卷，即使本次只运行不挂卷的 provision 服务。
        volumes=docker.call(['volume','ls','--format','{{.Name}}']).stdout.splitlines()
        if c['volume'] not in volumes:
            docker.call(['volume','create','--label','benchmark.deploy.project='+c['project'],
                         '--label','benchmark.deploy.root='+c['root'],c['volume']])
            docker.call(['run','--rm','--network','none','--user','root','--entrypoint','/bin/sh',
                '-v',c['volume']+':/data',c['image'],'-c','chown 10001:10001 /data'])
        info=json.loads(docker.call(['volume','inspect',c['volume']]).stdout)[0]
        labels=info.get('Labels') or {}
        if labels.get('benchmark.deploy.project')!=c['project'] or labels.get('benchmark.deploy.root')!=c['root']:
            raise DeployError('同名数据卷不属于本脚本的当前环境，未修改；请选择其他环境 ID')
        docker.call(['run','--rm','--network','none','--entrypoint','/bin/sh',
            '-v',c['volume']+':/data',c['image'],'-c','test -w /data'])
        result=docker.compose(directory,['run','--rm','robot-jetstream-provision','check'],check=False)
        try: report=json.loads(result.stdout)
        except ValueError as e: raise DeployError('JetStream 检查未返回有效结果，停止初始化') from e
        if any(stream.get('exists') for stream in report.get('streams',[])) and not (
            probe.get('owner_secret_hash') or probe['manifest_exists'] or probe['snapshot_exists']
        ):
            raise DeployError('NATS 上已存在同环境 Stream，但没有对应部署记录；请换独立环境 ID，避免消费其他环境事件')
        if not report.get('ok'):
            conflicts=report.get('conflicts',[])
            if not conflicts or any(x.get('kind')!='missing_stream' for x in conflicts):
                raise DeployError('JetStream 不可达或存在非缺失型冲突，未尝试覆盖')
        print('初始化 / 核对配置库……',flush=True)
        helper(docker,c,'claim')
        helper(docker,c,'import')
        helper(docker,c,'seed')
        helper(docker,c,'manifest')
        if not report.get('ok'):
            docker.compose(directory,['run','--rm','robot-jetstream-provision','reconcile',
                '--actor','interactive-deploy','--reason','initial-deployment'])
        docker.compose(directory,['up','-d'],capture=False)
        health=verify(docker,directory,c)
        print(f"基础服务验收通过。管理台：http://{c['bind'] if c['bind']!='0.0.0.0' else '<部署机地址>'}:{c['port']}/ui/")
        print('配置已保存到 '+str(directory)+'；再次运行 --dir 同目录可复用输入。')
        print('运维命令：'+shlex.join(docker.compose_command)+' --env-file '+shlex.quote(str(directory/'deployment.env'))+
              ' -f '+shlex.quote(str(directory/'docker-compose.yaml'))+' ps')
        report_business_readiness(c,health)
        print('脚本未创建或启动机器人任务；业务可用性以刚才显示的环境级状态为准。')


if __name__=='__main__':
    try: main()
    except KeyboardInterrupt:
        print('\n已中断。已创建的资源保留，不自动删除。',file=sys.stderr);sys.exit(130)
    except (DeployError,ValueError,OSError,subprocess.TimeoutExpired) as exc:
        print('部署停止：'+str(exc),file=sys.stderr);sys.exit(1)
