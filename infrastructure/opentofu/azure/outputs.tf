output "public_ip" {
  value = azurerm_public_ip.host.ip_address
}

output "resource_group" {
  value = azurerm_resource_group.titan.name
}

output "estimated_cost_warning" {
  value = "Free VM hours do not guarantee every attached resource is free. Check Cost Management, then destroy the resource group."
}

output "smoke_check_command" {
  value = "ssh -i <private-key> titan@${azurerm_public_ip.host.ip_address} 'sudo titan-health'"
}

output "portal_tunnel_command" {
  value = "ssh -i <private-key> -N -L 8090:127.0.0.1:8090 -L 8100:127.0.0.1:8100 -L 8200:127.0.0.1:8200 titan@${azurerm_public_ip.host.ip_address}"
}

output "token_command" {
  value = "ssh -i <private-key> titan@${azurerm_public_ip.host.ip_address} 'sudo cat /etc/titan/admin-token'"
}
