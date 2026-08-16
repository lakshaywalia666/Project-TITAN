# Packet-to-HTTP laboratory

Run `namespace-lab.sh` only inside a disposable Linux VM. It creates two explicitly
named namespaces and a bridge, proves reachability, and removes only those exact
objects on exit. Continue by running a small HTTP server in `titan-server`, capture
traffic with `tcpdump`, inspect DNS/TCP/TLS using `curl -v` and `openssl s_client`,
then add and remove one route deliberately.

