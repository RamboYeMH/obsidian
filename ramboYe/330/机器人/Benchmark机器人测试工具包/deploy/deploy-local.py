#!/usr/bin/env python3
"""本地 Agent 机器人测试部署入口。默认只预检，不会创建或修改服务。"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
from urllib.parse import urlsplit


class SetupError(RuntimeError):
    pass


def parse_env(path):
    values = {}
    if not path or not path.exists():
        return values
    for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            continue
        value = value.strip()
        if value.startswith(('"', "'")):
            try:
                parts = shlex.split(value, comments=False, posix=True)
                value = parts[0] if parts else ''
            except ValueError as exc:
                raise SetupError(f'{path}:{line_no}: 环境变量格式错误') from exc
        else:
            value = value.split(' #', 1)[0].strip()
        values[key] = value
    return values


def find_repo(value):
    candidates = []
    if value:
        candidates.append(Path(value).expanduser().resolve())
    for item in (Path.cwd(), Path(__file__).resolve().parents[2]):
        candidates.extend([item, *item.parents])
    for root in candidates:
        if (root / 'benchmark/deploy/benchmark-deploy.py').is_file() and (root / 'benchmark/Dockerfile').is_file():
            return root
    raise SetupError('找不到 gs 仓库；请用 --repo 指定包含 benchmark/ 的 gs 根目录')


def safe_slug(value):
    value = re.sub(r'[^a-z0-9-]+', '-', value.lower()).strip('-')
    return (value or 'local')[:22].strip('-') or 'local'


def local_settings(repo, env_file, args):
    file_values = parse_env(env_file)
    def pick(cli_name, env_name, file_names, default=''):
        explicit = getattr(args, cli_name, None)
        if explicit:
            return explicit
        for key in env_name:
            if os.environ.get(key):
                return os.environ[key]
        for key in file_names:
            if file_values.get(key):
                return file_values[key]
        return default

    host = pick('host', ('BENCHMARK_LOCAL_HOST',), ('BENCHMARK_LOCAL_HOST',), 'host.docker.internal')
    mongo = pick('mongo', ('BENCHMARK_LOCAL_MONGO_URI',), ('BENCHMARK_DBURL',),
                 f'mongodb://{host}:27017/?replicaSet=rs0')
    nats = pick('nats', ('BENCHMARK_LOCAL_NATS_URL',), ('ROBOT_NATS_URL',), f'nats://{host}:4222')
    etcd = pick('etcd', ('BENCHMARK_LOCAL_ETCD_ENDPOINTS',), ('BENCHMARK_ETCD_ENDPOINTS',), f'http://{host}:2379')
    gate = pick('gate', ('BENCHMARK_LOCAL_GATEADDR',), ('BENCHMARK_GATEADDR',), f'{host}:21001')
    image = pick('image', ('BENCHMARK_LOCAL_IMAGE',), (), 'gs-benchmark:local')
    short = safe_slug('benchmark-local-' + safe_slug(socket.gethostname()))
    env_id = pick('environment', ('BENCHMARK_LOCAL_ENV_ID',), ('BENCHMARK_LOCAL_ENV_ID',), short)
    database_suffix = safe_slug(env_id).replace('-', '_')[:35]
    target_dir = Path(args.dir).expanduser() if args.dir else Path.home() / '.local/share/benchmark' / env_id
    project = 'benchmark-' + safe_slug(env_id)
    settings = {
        'image': image,
        'environment': env_id,
        'mongo': mongo,
        'nats': nats,
        'etcd': etcd,
        'gate': gate,
        'server': pick('server', ('BENCHMARK_LOCAL_SERVER_ID',), ('BENCHMARK_LOCAL_SERVER_ID',), '1'),
        'database': 'gs_benchmark_' + database_suffix,
        'config_mode': 'import',
        'csv': 'gs_conf_benchmark_' + database_suffix,
        'root': '/benchmark/' + env_id + '/docker/runtime-config',
        'secret': '',
        'generated_secret': False,
        'auth': 'bypass',
        'bind': '127.0.0.1',
        'port': pick('manager_port', ('BENCHMARK_LOCAL_MANAGER_PORT',), ('BENCHMARK_LOCAL_MANAGER_PORT',), '28082'),
        'portal_url': '', 'portal_app': '', 'portal_callback': '',
        'project': project, 'volume': project + '-worker-data',
        'network': project + '_default', 'worker': 'worker-' + safe_slug(env_id) + '-1',
        'build': '', 'image_build': '', 'enable_block_test': True,
        'toolkit_managed': True,
    }
    return target_dir.resolve(), settings


def endpoint_host_port(value, kind):
    if kind == 'mongodb':
        if not value.startswith(('mongodb://', 'mongodb+srv://')):
            raise SetupError('Mongo URI 必须以 mongodb:// 或 mongodb+srv:// 开头')
        raw = value.split('://', 1)[1].split('/', 1)[0].rsplit('@', 1)[-1]
        out = []
        for entry in raw.split(','):
            if entry.startswith('['):
                host, _, port = entry[1:].partition(']')
                port = port.lstrip(':') or '27017'
            else:
                host, sep, port = entry.rpartition(':')
                if not sep:
                    host, port = entry, '27017'
            out.append((host, int(port)))
        return out
    if kind == 'nats':
        u = urlsplit(value)
        if u.scheme not in ('nats', 'tls') or not u.hostname:
            raise SetupError('NATS URL 格式无效')
        return [(u.hostname, u.port or 4222)]
    if kind == 'etcd':
        out = []
        for item in value.split(','):
            u = urlsplit(item if '://' in item else 'http://' + item)
            if u.scheme not in ('http', 'https') or not u.hostname:
                raise SetupError('etcd 地址格式无效')
            out.append((u.hostname, u.port or (443 if u.scheme == 'https' else 2379)))
        return out
    host, sep, port = value.rpartition(':')
    if not sep:
        raise SetupError('Gate 地址必须为 host:port')
    return [(host.strip('[]'), int(port))]


def tcp_check(host, port, timeout=2):
    candidates = [host]
    if host == 'host.docker.internal':
        try:
            net = json.loads(subprocess.check_output(['docker', 'network', 'inspect', 'bridge'], text=True))[0]
            gateway = net.get('IPAM', {}).get('Config', [{}])[0].get('Gateway')
            if gateway:
                candidates.append(gateway)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, IndexError, KeyError):
            pass
    for candidate in candidates:
        try:
            with socket.create_connection((candidate, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def preflight(repo, target, settings, args):
    for command in ('python3', 'docker'):
        if not shutil.which(command):
            raise SetupError(f'缺少命令：{command}')
    subprocess.run(['docker', 'info'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['docker', 'compose', 'version'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for rel in ('benchmark/backend/internal/aiblockassistant/protocol_catalog.json.gz',
                'benchmark/backend/internal/robotaction/catalog.json'):
        if not (repo / rel).is_file():
            raise SetupError(f'缺少镜像构建所需嵌入文件：{rel}')
    dependencies = [('Mongo', endpoint_host_port(settings['mongo'], 'mongodb')),
                    ('NATS', endpoint_host_port(settings['nats'], 'nats')),
                    ('etcd', endpoint_host_port(settings['etcd'], 'etcd'))]
    for label, endpoints in dependencies:
        if not any(tcp_check(h, p) for h, p in endpoints):
            places = ', '.join(f'{h}:{p}' for h, p in endpoints)
            raise SetupError(f'{label} TCP 不可达（{places}）；确认依赖已启动且容器可通过 host.docker.internal 或本机 IP 访问')
    gate = endpoint_host_port(settings['gate'], 'gate')[0]
    if not tcp_check(*gate):
        print(f'提示：Gate {gate[0]}:{gate[1]} 当前不可达；可部署管理台，但机器人无法登录，运行测试前需恢复 Gate。')
    if args.require_image:
        subprocess.run(['docker', 'image', 'inspect', settings['image']], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('本地预检通过：Docker/Compose、镜像构建输入及 Mongo/NATS/etcd 连接均可用。')
    print(f'部署环境 ID：{settings["environment"]}；管理台仅绑定 127.0.0.1:{settings["port"]}。')
    print('连接字符串与凭据不会打印。Block 自测试仅在这套本机部署中开启。')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', help='gs 仓库根目录；默认从当前目录向上查找')
    ap.add_argument('--env-file', help='本机依赖连接配置；默认读取 <repo>/benchmark/envs/h5-local.env（仅本机读取，不复制）')
    ap.add_argument('--dir', help='私有部署目录；默认 ~/.local/share/benchmark/<environment>')
    ap.add_argument('--host', help='容器访问宿主机的地址，默认 host.docker.internal')
    ap.add_argument('--mongo', help='Mongo 副本集 URI；默认读取 env-file 的 BENCHMARK_DBURL')
    ap.add_argument('--nats', help='NATS URL；默认读取 env-file 的 ROBOT_NATS_URL')
    ap.add_argument('--etcd', help='etcd v3 HTTP gateway 地址；默认读取 env-file 的 BENCHMARK_ETCD_ENDPOINTS')
    ap.add_argument('--gate', help='游戏 Gate host:port；默认读取 env-file 的 BENCHMARK_GATEADDR')
    ap.add_argument('--image', help='本机镜像标签；默认 gs-benchmark:local')
    ap.add_argument('--preflight', action='store_true', help='只检查本机工具和外部依赖连接，不写文件或启动服务')
    ap.add_argument('--prepare-only', action='store_true', help='仅私有生成配置并校验 Compose，不启动或写入依赖')
    ap.add_argument('--deploy', action='store_true', help='执行首次部署；唯一部署确认由本命令显式表达')
    ap.add_argument('--check', action='store_true', help='对已部署环境做只读依赖检查')
    ap.add_argument('--start', action='store_true', help='启动已有本机部署')
    ap.add_argument('--stop', action='store_true', help='排空后停止已有本机部署')
    a = ap.parse_args()
    if sum((a.preflight, a.prepare_only, a.deploy, a.check, a.start, a.stop)) != 1:
        ap.error('选择且只选择 --preflight、--prepare-only、--deploy、--check、--start 或 --stop')
    repo = find_repo(a.repo)
    env_file = Path(a.env_file).expanduser() if a.env_file else repo / 'benchmark/envs/h5-local.env'
    target, settings = local_settings(repo, env_file, a)
    if a.preflight:
        if (target / 'deploy-settings.json').exists():
            raise SetupError(f'部署目录已有正式配置，拒绝覆盖：{target}。请用 --check/--start/--stop。')
        preflight(repo, target, settings, argparse.Namespace(require_image=False))
        return 0
    if a.check or a.start or a.stop:
        cmd = [sys.executable, str(Path(__file__).with_name('benchmark-deploy.py'))]
        cmd += ['--dir', str(target), '--check' if a.check else '--start' if a.start else '--stop']
        return subprocess.run(cmd).returncode
    if a.deploy and (target / 'deploy-settings.json').exists():
        raise SetupError(f'部署目录已有正式配置，拒绝覆盖：{target}。请用 --check/--start/--stop 或另选 --dir。')
    preflight(repo, target, settings, argparse.Namespace(require_image=a.deploy))
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (target / 'deploy-settings.json').exists():
        raise SetupError('目标目录已有 deploy-settings.json；拒绝覆盖已有部署配置')
    answers = target / 'answers.json'
    fd = os.open(answers, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(settings, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    script = Path(__file__).with_name('benchmark-deploy.py')
    command = [sys.executable, str(script), '--dir', str(target), '--local-image', '--non-interactive']
    if a.prepare_only:
        command.append('--prepare-only')
    else:
        command.append('--yes')
    print('部署参数已写入权限为 600 的本机文件；不会输出 Mongo URI 或密钥。')
    return subprocess.run(command).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SetupError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('部署入口失败：' + (str(exc) if isinstance(exc, SetupError) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
