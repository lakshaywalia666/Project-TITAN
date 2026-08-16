locals {
  bootstrap = templatefile("${path.module}/../shared/bootstrap-titan.sh.tftpl", {
    titan_image = var.titan_image
  })
  tags = {
    Project   = "titan"
    ManagedBy = "opentofu"
    Owner     = var.owner
    Expires   = var.expires_at
  }
}

resource "azurerm_resource_group" "titan" {
  name     = var.name
  location = var.location
  tags     = local.tags
}

resource "azurerm_virtual_network" "titan" {
  name                = "${var.name}-vnet"
  address_space       = ["10.91.0.0/16"]
  location            = azurerm_resource_group.titan.location
  resource_group_name = azurerm_resource_group.titan.name
  tags                = local.tags
}

resource "azurerm_subnet" "host" {
  name                 = "host"
  resource_group_name  = azurerm_resource_group.titan.name
  virtual_network_name = azurerm_virtual_network.titan.name
  address_prefixes     = ["10.91.10.0/24"]
}

resource "azurerm_network_security_group" "host" {
  name                = "${var.name}-host"
  location            = azurerm_resource_group.titan.location
  resource_group_name = azurerm_resource_group.titan.name
  tags                = local.tags
  security_rule {
    name                       = "ssh-from-operator"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.operator_cidr
    destination_address_prefix = "*"
  }
}

resource "azurerm_public_ip" "host" {
  name                = "${var.name}-host"
  location            = azurerm_resource_group.titan.location
  resource_group_name = azurerm_resource_group.titan.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_network_interface" "host" {
  name                = "${var.name}-host"
  location            = azurerm_resource_group.titan.location
  resource_group_name = azurerm_resource_group.titan.name
  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.host.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.host.id
  }
  tags = local.tags
}

resource "azurerm_network_interface_security_group_association" "host" {
  network_interface_id      = azurerm_network_interface.host.id
  network_security_group_id = azurerm_network_security_group.host.id
}

resource "azurerm_linux_virtual_machine" "host" {
  name                            = var.name
  location                        = azurerm_resource_group.titan.location
  resource_group_name             = azurerm_resource_group.titan.name
  size                            = var.vm_size
  admin_username                  = "titan"
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.host.id]
  custom_data                     = base64encode(local.bootstrap)
  admin_ssh_key {
    username   = "titan"
    public_key = var.ssh_public_key
  }
  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 30
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }
  identity { type = "SystemAssigned" }
  tags = local.tags
  lifecycle {
    precondition {
      condition     = var.vm_size == "Standard_B1s"
      error_message = "The x86 smoke lab permits only Standard_B1s; subscription eligibility must still be verified."
    }
  }
}
