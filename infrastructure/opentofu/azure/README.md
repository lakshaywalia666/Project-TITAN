# Azure disposable smoke VM

Creates one `Standard_B1s` Ubuntu 22.04 VM with a 30 GB Standard LRS OS disk, a
resource group, virtual network, subnet, network security group, NIC and Standard
public IP. Only SSH from the supplied `/32` is allowed; application ports remain
on VM loopback. No load balancer, NAT gateway, database or managed Kubernetes
service is created.

The Standard public IP and other related resources can be billable even when VM
compute is covered by an offer. Check the plan and Azure Cost Management before
applying. The common image, bootstrap and smoke flow are documented in the
[three-cloud guide](../README.md).

Use GitHub OIDC with a dedicated learning identity scoped to a disposable
subscription or resource group. After every run, confirm the entire generated
resource group was deleted in the Azure portal.
