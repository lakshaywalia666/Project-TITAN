# Titan host configuration

The role installs the repository Python source, a protected environment file and
four hardened systemd services bound to loopback. Put the bootstrap token in an
Ansible Vault file; do not pass it in shell history for a real host.
Set the optional `titan_jwt_secret` to at least 32 characters only for the signed
local-identity lab; otherwise leave it empty.

```bash
cp inventory.example.ini inventory.ini
ansible-vault create secrets.yml
# titan_admin_token: a-long-random-value
ansible-playbook -i inventory.ini site.yml --ask-vault-pass -e @secrets.yml
```

Run the playbook twice: the second run should report no changes. Introduce controlled
drift in a disposable VM and verify only affected units restart.
