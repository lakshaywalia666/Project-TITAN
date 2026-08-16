output "public_ip" {
  value = google_compute_instance.host.network_interface[0].access_config[0].nat_ip
}

output "instance_name" {
  value = google_compute_instance.host.name
}

output "estimated_cost_warning" {
  value = "Free Tier applies only within documented region, VM-hour, pd-standard disk and egress limits. Verify Billing and destroy after the check."
}

output "smoke_check_command" {
  value = "ssh -i <private-key> titan@${google_compute_instance.host.network_interface[0].access_config[0].nat_ip} 'sudo titan-health'"
}

output "portal_tunnel_command" {
  value = "ssh -i <private-key> -N -L 8090:127.0.0.1:8090 -L 8100:127.0.0.1:8100 -L 8200:127.0.0.1:8200 titan@${google_compute_instance.host.network_interface[0].access_config[0].nat_ip}"
}

output "token_command" {
  value = "ssh -i <private-key> titan@${google_compute_instance.host.network_interface[0].access_config[0].nat_ip} 'sudo cat /etc/titan/admin-token'"
}
