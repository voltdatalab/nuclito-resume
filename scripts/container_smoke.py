"""CI-only smoke of the production Docker CMD; no published ports or provider I/O.

Run after docker/build-push-action loads the local image. MySQL is the disposable
Actions service container, not a remote or production database. No CMD override.
"""
import argparse
import json
import os
import subprocess
import time
import uuid


def docker(*args, timeout=20, check=True):
    return subprocess.run(['docker', *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--mysql-container', required=True)
    args = parser.parse_args()
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        parser.error('Only disposable GitHub-hosted CI runners are admitted')
    suffix = uuid.uuid4().hex
    network, container = 'nuclito-smoke-' + suffix, 'nuclito-api-' + suffix
    network_created = attached = container_created = False
    try:
        docker('network', 'create', '--internal', network)
        network_created = True
        assert json.loads(docker('network', 'inspect', network))[0]['Internal'] is True
        docker('network', 'connect', '--alias', 'mysql', network, args.mysql_container)
        attached = True
        # Entrypoint creates the REAL posts schema in a separate empty fixture DB.
        docker('exec', args.mysql_container, 'mysql', '-uroot', '-pfixture-root-only',
               '-e', 'CREATE DATABASE nuclito_runtime CHARACTER SET utf8mb4')
        env = dict(DB_ENGINE='mysql', DB_HOST='mysql', DB_PORT='3306',
                   DB_DATABASE='nuclito_runtime', DB_USERNAME='root',
                   DB_PASSWORD='fixture-root-only', PYTHON_DOTENV_DISABLED='1',
                   OPENAI_API_KEY='sk-synthetic-no-provider-call',
                   WEBHOOK_SECRET='synthetic-ci-webhook-only', PUBLICATION_SYNC_ENABLED='1')
        options = [part for key, value in env.items() for part in ('--env', key + '=' + value)]
        docker('run', '--detach', '--name', container, '--network', network,
               '--cap-drop=ALL', '--security-opt=no-new-privileges',
               '--memory=512m', '--cpus=1', '--pids-limit=128', *options, args.image)
        container_created = True
        state = json.loads(docker('inspect', container))[0]
        assert state['Config']['Cmd'] == ['/bin/sh', '-c', 'python /app/main.py']
        assert set(state['NetworkSettings']['Networks']) == {network}
        assert not state['HostConfig']['PortBindings']
        probe = (
            "import json,urllib.request; "
            "r=urllib.request.urlopen('http://127.0.0.1:8000/',timeout=2); "
            "assert r.status==200; assert json.load(r)=={'Hello':'World'}"
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                docker('exec', container, 'python', '-c', probe, timeout=5)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if time.monotonic() >= deadline:
                    raise RuntimeError('Actual production CMD did not become healthy within 60s') from None
                time.sleep(1)
        schema = (
            "from sqlalchemy import inspect; from app.model import engine; "
            "from app.models.posts import Post; "
            "assert set(inspect(engine).get_table_names())=={'posts'}; "
            "assert {c['name'] for c in inspect(engine).get_columns('posts')}==set(Post.__table__.c.keys())"
        )
        docker('exec', container, 'python', '-c', schema)
        print(docker('exec', container, 'python', '-c',
                     "import json,sys; from importlib.metadata import version; "
                     "assert sys.version_info[:2]==(3,10); "
                     "print(json.dumps({'python':sys.version.split()[0], "
                     "'packages':{p:version(p) for p in ['fastapi','uvicorn','sqlalchemy','mysqlclient','openai']}}))"))
        docker('exec', container, 'python', '-m', 'app.publication_cli', 'schema', '--apply')
        docker('exec', container, 'python', '-c',
               "from sqlalchemy import inspect; from app.model import engine; "
               "assert set(inspect(engine).get_table_names())=="
               "{'posts','publication_inbox','publication_reconcile_cursor'}")
        # GETs exercise real DB-backed routing. No POST, worker, LLM or CMS call.
        docker('exec', container, 'python', '-c',
               "import json,urllib.request,urllib.error; "
               "r=urllib.request.urlopen('http://127.0.0.1:8000/post/',timeout=3); "
               "assert r.status==200 and json.load(r)==[]; "
               "\ntry: urllib.request.urlopen('http://127.0.0.1:8000/post/'+'a'*24,timeout=3)"
               "\nexcept urllib.error.HTTPError as error: assert error.code==404"
               "\nelse: raise AssertionError('Expected missing synthetic post')")
        print('Production CMD HTTP 200; real posts + explicit inbox schema; empty reads; no LLM/CMS calls.')
    finally:
        # Never emit application logs: future failures might contain diagnostic payloads.
        if container_created:
            docker('rm', '--force', container, check=False)
        if attached:
            docker('network', 'disconnect', network, args.mysql_container, check=False)
        if network_created:
            docker('network', 'rm', network, check=False)


if __name__ == '__main__':
    main()
