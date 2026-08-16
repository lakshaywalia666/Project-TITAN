data "aws_ssm_parameter" "ubuntu_2204_amd64" {
  name = "/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

locals {
  bootstrap = templatefile("${path.module}/../shared/bootstrap-titan.sh.tftpl", {
    titan_image = var.titan_image
  })
  tags = {
    Name      = var.name
    Purpose   = "disposable-smoke-test"
    ExpiresAt = var.expires_at
  }
}

resource "aws_vpc" "titan" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = local.tags
}

resource "aws_internet_gateway" "titan" {
  vpc_id = aws_vpc.titan.id
  tags   = merge(local.tags, { Name = "${var.name}-igw" })
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.titan.id
  cidr_block              = var.public_subnet_cidr
  map_public_ip_on_launch = true
  tags                    = merge(local.tags, { Name = "${var.name}-public" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.titan.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.titan.id
  }
  tags = merge(local.tags, { Name = "${var.name}-public" })
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "host" {
  name        = "${var.name}-host"
  description = "Restricted administrative access to Titan lab host"
  vpc_id      = aws_vpc.titan.id

  ingress {
    description = "SSH from the explicitly trusted operator address"
    protocol    = "tcp"
    from_port   = 22
    to_port     = 22
    cidr_blocks = [var.operator_cidr]
  }

  egress {
    description = "Outbound package and source access"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${var.name}-host" })
}

resource "aws_key_pair" "operator" {
  key_name   = "${var.name}-operator"
  public_key = var.ssh_public_key
}

resource "aws_instance" "host" {
  ami                         = var.ami_id != "" ? var.ami_id : data.aws_ssm_parameter.ubuntu_2204_amd64.value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.host.id]
  key_name                    = aws_key_pair.operator.key_name
  associate_public_ip_address = true
  monitoring                  = false
  user_data                   = local.bootstrap
  user_data_replace_on_change = true

  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 12
  }

  tags = local.tags

  lifecycle {
    precondition {
      condition     = contains(["t2.micro", "t3.micro"], var.instance_type)
      error_message = "The smoke lab permits only t2.micro or t3.micro. Eligibility still depends on the account offer."
    }
  }
}
