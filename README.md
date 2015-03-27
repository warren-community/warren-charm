# Overview

Warren is a networked content-sharing site, allowing users to not only post
their creations, but link them together into a web of their works, and the works
of others.  It manages each post as an abstract entity and uses content types to
render those abstract types into something viewable within a browser.

# Usage

This charm is meant to be deployed with several other charms in order to provide
a running environment that contains storage, search, and load-balancer
capabilities.  An example deployment would look like the following:

    juju deploy local:trusty/warren-charm
    juju deploy cs:trusty/mongo
    juju deploy cs:trusty/elasticsearch
    juju deploy cs:trusty/haproxy

    juju add-relation warren-charm mongo
    juju add-relation warren-charm elasticsearch
    juju add-relation warren-charm haproxy
    juju expose haproxy

In the future, it may be advisable to simply manage this deployment through a
bundle.

# Configuration

No configuration values are currently defined.

# Contact Information

- Warren: [warren.community](http://warren.community)
- Warren source/issues: [GitHub](http://github.com/warren-community/warren)
- Warren charm source/issues: [GitHub](http://github.com/warren-community/warren-charm)
