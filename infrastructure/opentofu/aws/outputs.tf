output "instance_id" {
  value = aws_instance.host.id
}

output "public_ip" {
  value = aws_instance.host.public_ip
}

output "estimated_cost_warning" {
  value = "Free-tier eligibility is account-specific. Verify Billing, run the smoke check, destroy, and confirm resource deletion."
}

output "smoke_check_command" {
  value = "ssh -i <private-key> ubuntu@${aws_instance.host.public_ip} 'sudo titan-health'"
}

output "portal_tunnel_command" {
  value = "ssh -i <private-key> -N -L 8090:127.0.0.1:8090 -L 8100:127.0.0.1:8100 -L 8200:127.0.0.1:8200 ubuntu@${aws_instance.host.public_ip}"
}

output "token_command" {
  value = "ssh -i <private-key> ubuntu@${aws_instance.host.public_ip} 'sudo cat /etc/titan/admin-token'"
}
