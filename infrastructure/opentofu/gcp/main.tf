locals {
  bootstrap = templatefile("${path.module}/../shared/bootstrap-titan.sh.tftpl", {
    titan_image = var.titan_image
  })
  expires_label = replace(lower(var.expires_at), ":", "-")
}

resource "google_compute_network" "titan" {
  name                    = var.name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "host" {
  name          = "${var.name}-host"
  ip_cidr_range = "10.92.10.0/24"
  region        = var.region
  network       = google_compute_network.titan.id
}

resource "google_compute_firewall" "ssh" {
  name          = "${var.name}-ssh"
  network       = google_compute_network.titan.name
  source_ranges = [var.operator_cidr]
  target_tags   = ["titan-host"]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_service_account" "host" {
  account_id   = "titan-lab-host"
  display_name = "Titan lab host with no project roles"
}

resource "google_compute_instance" "host" {
  name                      = var.name
  machine_type              = var.machine_type
  zone                      = var.zone
  allow_stopping_for_update = true
  tags                      = ["titan-host"]
  labels = {
    project    = "titan"
    owner      = lower(replace(var.owner, "_", "-"))
    managed-by = "opentofu"
    expires    = local.expires_label
  }
  boot_disk {
    initialize_params {
      image = "ubuntu-os-cloud/ubuntu-2204-lts"
      size  = 20
      type  = "pd-standard"
    }
  }
  network_interface {
    subnetwork = google_compute_subnetwork.host.id
    access_config {}
  }
  metadata = {
    block-project-ssh-keys = "true"
    ssh-keys               = "titan:${var.ssh_public_key}"
  }
  metadata_startup_script = local.bootstrap
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  service_account {
    email  = google_service_account.host.email
    scopes = ["https://www.googleapis.com/auth/logging.write", "https://www.googleapis.com/auth/monitoring.write"]
  }
  lifecycle {
    precondition {
      condition     = var.machine_type == "e2-micro"
      error_message = "The free-tier smoke lab permits only e2-micro."
    }
    precondition {
      condition     = startswith(var.zone, "${var.region}-")
      error_message = "zone must belong to the selected region."
    }
  }
}
