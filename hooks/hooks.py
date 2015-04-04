#!/usr/bin/python

import apt
import os
import subprocess
import sys

from shutil import rmtree
from string import Template

# Charm helper bits
charm_dir = os.environ['CHARM_DIR']
sys.path.insert(0, os.path.join(charm_dir, 'lib'))

from charmhelpers.core import (
    hookenv,
    host,
)

config = hookenv.config()
hooks = hookenv.Hooks()
log = hookenv.log
relations = hookenv.relations()

# Configuration
dependencies = ('git', 'golang-go')
owner = 'warren'
application = 'warren'
unit_name = os.environ['JUJU_UNIT_NAME']
service = unit_name[:unit_name.index('/')]
system_service = '{}-{}'.format(application, service)
upstart_conf = '/etc/init.d/{}.conf'.format(system_service)
service_dir = '/srv/{}'.format(system_service)
config_dir = '{}/etc'.format(service_dir)
config_yaml = '{}/config.yaml'.format(config_dir)
install_dir = '{}/{}'.format(service_dir, application)
package = 'github.com/warren-charm/warren'

# Utility functions
def run(*popenargs, **kwargs):
    if 'user' in kwargs:
        uid = pwd.getpwnam(kwargs['user']).pw_uid
        del kwargs['user']
        kwargs['preexec_fn'] = lambda: os.seteuid(uid)
    subprocess.check_call(*popenargs, **kwargs)

def unlink_if_exists(path):
    if os.path.exists(path):
        os.unlink(path)

# Unit functions
def ensure_packages(*pkgs):
    '''
    ensure_packages installs and upgrades pacakges. The goal is to be apt-get
    install equivalent.
    '''
    apt.apt_pkg.config['APT::Install-Recommends'] = '0'
    apt.apt_pkg.config['APT::Get::Assume-Yes'] = '1'
    cache = apt.Cache()
    for name in pkgs:
        pkg = cache[name]
        if not pkg.is_installed:
            pkg.mark_install()
        if pkg.is_upgradable:
            pkg.mark_upgrade()
    cache.commit()

def restart():
    log('(re)starting ' + system_service)
    host.service_restart(system_service) or \
        host.service_start(system_service)

# Hook helpers
def relation_param(relation, name, default=None):
    for rel in relations.get(relation, {}).itervalues():
        for unit in rel.itervalues():
            if name in unit:
                return unit.get(name, default)
    return default

def install_from_source():
    rmtree('{}/src'.format(install_dir), True)
    package_dir = '{}/src/{}'.format(install_dir, package)
    os.environ['GOPATH'] = install_dir
    os.environ['PATH'] = '{}:{}'.format(
        os.path.join(install_dir, 'bin'),
        os.environ['PATH'])
    run(('go', 'get', package), user=owner)
    run(('git', 'fetch', '--tags', 'origin'), cwd=package_dir, user=owner)
    source_type, source_name = config['source'].split(':')
    if source_type == 'branch':
        run(('git', 'checkout', branch), cwd=package_dir, user=owner)
    elif source_type == 'tag':
        run(('git', 'checkout', '-b', 'tag-{}'.format(source_name),
            source_name), cwd=package_dir, user=owner)
    elif source_type == 'commit':
        run(('git', 'reset', '--hard', source_name), cwd=package_dir,
            user=owner)
    else:
        # default to master
        run(('git', 'checkout', 'master'), cwd=package_dir, user=owner)
    run(('make', 'deps'), cwd=package_dir, user=owner)
    run(('make', 'install'), cwd=package_dir, user=owner)

def write_init_file():
    with open(os.path.join(charm_dir, 'templates', 'init.tmpl')) as r:
        tmpl = Template(r.read())
    host.write_file(
        upstart_conf, tmpl.substitute({'dir': service_dir}))

def write_config_file():
    mongo_host = relation_param(mongo_relation, 'hostname')
    mongo_port = relation_param(mongo_relation, 'port')
    es_host, es_port = get_es_endpoint()
    params = {
        'session_auth_key': config['session-auth-key'],
        'session_encryption_key': config['session-encryption-key'],
        'mongo_host': '{}:{}'.format(mongo_host, mongo_port),
        'mongo_db': config['mongo-db'],
        'elasticsearch_host': es_host,
        'elasticsearch_port': es_port,
        'SMTP_host': config['smtp-server'],
    }
    mongo_up = bool(mongo_host and mongo_port)
    es_up = bool(es_host and es_port)
    with open(config_yaml) as r:
        tmpl = Template(r.read())
    host.write_file(
        config_yaml, tmpl.substitute(params), owner=owner, group=owner)
    log('Wrote {}'.format(config_yaml))
    return (mongo_up, es_up)

def manage_ports():
    if config.changed(listen_port_key):
        if config.previous(listen_port_key) is not None:
            msg = "close-port {}".format(config.previous(listen_port_key))
            print(msg)
            log(msg)
            hookenv.close_port(config.previous(listen_port_key))
        listen_port = config[listen_port_key]
        msg = "open-port {}".format(listen_port)
        print(msg)
        log(msg)
        hookenv.open_port(listen_port)
        update_website_relations()

# Hooks
@hooks.hook('install')
def install():
    ensure_packages(*dependencies)    
    host.adduser(owner)

@hooks.hook('website-relation-joined')
@hooks.hook('website-relation-departed')
@hooks.hook('website-relation-broken')
@hooks.hook('website-relation-changed')
def website_relation_hook():
    for relation_id in relations.get('website', {}).keys():
        private_address = hookenv.unit_private_ip()
        hookenv.relations_set(
            relation_id=relation_id,
            relation_settings={'hostname': private_address, 'port': config['listen_port']})

@hooks.hook('stop')
def stop():
    host.service_stop(system_service)
    if upstart_conf:
        unlink_if_exists(upstart_conf)
    
@hooks.hook('start')
@hooks.hook('config-changed')
@hooks.hook('mongodb-relation-joined')
@hooks.hook('mongodb-relation-departed')
@hooks.hook('mongodb-relation-broken')
@hooks.hook('mongodb-relation-changed')
@hooks.hook('elasticsearch-relation-joined')
@hooks.hook('elasticsearch-relation-departed')
@hooks.hook('elasticsearch-relation-broken')
@hooks.hook('elasticsearch-relation-changed')
def main_hook():
    write_init_file()
    write_config_file()
    restart()

if __name__ == '__main__':
    pass
