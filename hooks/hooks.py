#!/usr/bin/python

import apt
import os
import pwd
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
dependencies = ('git', 'golang-go', 'make', 'bzr')
owner = 'warren'
application = 'warren'
package = 'github.com/warren-community/warren'
unit_name = os.environ['JUJU_UNIT_NAME']
service = unit_name[:unit_name.index('/')]
system_service = '{}-{}'.format(application, service)
upstart_conf = '/etc/init/{}.conf'.format(system_service)
service_dir = '/srv/{}'.format(system_service)
config_dir = '{}/etc'.format(service_dir)
config_yaml = '{}/warren-config.yaml'.format(config_dir)
install_dir = '{}/{}'.format(service_dir, application)
package_dir = '{}/src/{}'.format(install_dir, package)

def run(*popenargs, **kwargs):
    '''Run a command as a given user'''
    if 'user' in kwargs:
        uid = pwd.getpwnam(kwargs['user']).pw_uid
        del kwargs['user']
        kwargs['preexec_fn'] = lambda: os.seteuid(uid)
    subprocess.check_call(*popenargs, **kwargs)

def unlink_if_exists(path):
    '''Remove a file if it exists.'''
    if os.path.exists(path):
        os.unlink(path)

def apt_get_update():
    '''Update packages on the system.'''
    apt.apt_pkg.config['APT::Install-Recommends'] = '0'
    cache = apt.Cache()
    try:
        cache.update()
        cache.open(None)
        cache.commit()
    except Exception as e:
        msg = "apt_get_update error:{}".format(e)
        log(msg)
        print(msg)

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
    '''(Re)start the warren service'''
    log('(re)starting ' + system_service)
    host.service_restart(system_service) or \
        host.service_start(system_service)

def relation_param(relation, name, default=None):
    '''Retrieve a given relation's information, optionally returning a default
    if nothing is found.
    '''
    for rel in relations.get(relation, {}).itervalues():
        for unit in rel.itervalues():
            if name in unit:
                return unit.get(name, default)
    return default

def prep_installation():
    host.mkdir(service_dir, owner=owner, group=owner)
    host.mkdir(install_dir, owner=owner, group=owner, perms=0755)
    host.mkdir(config_dir, owner=owner, group=owner)

def install_from_source():
    '''(Re)install the warren source and use the proper branch.'''
    log('installing warren from source')
    rmtree('{}/src'.format(install_dir), True)
    os.environ['GOPATH'] = install_dir
    os.environ['PATH'] = '{}:{}'.format(
        os.path.join(install_dir, 'bin'),
        os.environ['PATH'])
    run(('go', 'get', '{}/...'.format(package)), user=owner)
    run(('git', 'fetch', '--tags', 'origin'), cwd=package_dir, user=owner)
    source_type, source_name = config['source'].split(':')
    if source_type == 'branch':
        run(('git', 'checkout', source_name), cwd=package_dir, user=owner)
    elif source_type == 'tag':
        run(('git', 'checkout', '-b', 'tag-{}'.format(source_name),
            source_name), cwd=package_dir, user=owner)
    elif source_type == 'commit':
        run(('git', 'reset', '--hard', source_name), cwd=package_dir,
            user=owner)
    else:
        # default to master
        run(('git', 'checkout', 'master'), cwd=package_dir, user=owner)
    run(('make', 'godeps'), cwd=package_dir, user=owner)
    run(('make', 'deps'), cwd=package_dir, user=owner)
    run(('make', 'install'), cwd=package_dir, user=owner)

def write_init_file():
    '''Write the init file.'''
    log('writing upstart file')
    with open(os.path.join(charm_dir, 'templates', 'upstart.conf')) as r:
        tmpl = Template(r.read())
    host.write_file(
        upstart_conf, tmpl.substitute({'owner': owner, 'dir': service_dir}))

def write_config_file():
    '''Write the warren config file.'''
    log('writing config file')
    mongo_host = relation_param('mongodb', 'hostname')
    mongo_port = relation_param('mongodb', 'port')
    es_host = relation_param('elasticsearch', 'host')
    es_port = relation_param('elasticsearch', 'port', '9200')
    params = {
        'template_dir': '{}/templates'.format(package_dir),
        'static_dir': '{}/public'.format(package_dir),
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
    with open(os.path.join(charm_dir, 'templates', 'config.yaml')) as r:
        tmpl = Template(r.read())
    log('Writing params: {}'.format(params))
    host.write_file(
        config_yaml, tmpl.substitute(params), owner=owner, group=owner)
    log('Wrote {}'.format(config_yaml))
    return (mongo_up, es_up)

def manage_ports():
    '''Open/close ports if necessary'''
    log('checking ports')
    if config.changed('listen-port'):
        if config.previous('listen-port') is not None:
            msg = "close-port {}".format(config.previous('listen-port'))
            print(msg)
            log(msg)
            hookenv.close_port(config.previous('listen-port'))
        listen_port = config['listen-port']
        msg = "open-port {}".format(listen_port)
        print(msg)
        log(msg)
        hookenv.open_port(listen_port)
        update_website_relations()

@hooks.hook('install')
def install():
    '''Install required packages, user, and warren source.'''
    apt_get_update()
    ensure_packages(*dependencies)    
    host.adduser(owner)
    prep_installation()
    install_from_source()

@hooks.hook('website-relation-joined')
@hooks.hook('website-relation-departed')
@hooks.hook('website-relation-broken')
@hooks.hook('website-relation-changed')
def website_relation_hook():
    '''Notify all website relations of our address and port.'''
    for relation_id in relations.get('website', {}).keys():
        private_address = hookenv.unit_private_ip()
        hookenv.relation_set(
            relation_id=relation_id,
            relation_settings={'hostname': private_address, 'port': config['listen_port']})

@hooks.hook('stop')
def stop():
    '''Stop the warren service.'''
    log('Stopping service...')
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
    '''Main hook functionality

    On most hooks, we simply need to write config files, work with hooks, and
    restart.  If the source has changed, we'll additionally need to rebuild.
    '''
    if config.changed('source'):
        log('Source changed; rebuilding...')
        install_from_source()
    write_init_file()
    write_config_file()
    manage_ports()
    restart()

if __name__ == "__main__":
    hooks.execute(sys.argv)
