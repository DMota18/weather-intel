terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.5"
}

provider "aws" {
  region = var.aws_region
}

# --- Security Group ---
resource "aws_security_group" "weather_intel" {
  name        = "weather-intel-sg"
  description = "Weather Intel Platform security group"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_ip]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "PostgreSQL (Tableau)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.admin_ip]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "weather-intel"
    Project = "weather-intel"
  }
}

# --- EC2 Instance ---
resource "aws_instance" "weather_intel" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.weather_intel.id]

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -qq
    apt-get install -y -qq postgresql-16 redis-server nginx python3-venv certbot python3-certbot-nginx
    systemctl enable postgresql@16-main redis-server nginx
  EOF

  tags = {
    Name    = "weather-intel"
    Project = "weather-intel"
  }
}

# --- S3 Bucket for Backups ---
resource "aws_s3_bucket" "backups" {
  bucket = "nesc-weather-intel-backups"

  tags = {
    Name    = "weather-intel-backups"
    Project = "weather-intel"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backup_retention" {
  bucket = aws_s3_bucket.backups.id

  rule {
    id     = "delete-old-backups"
    status = "Enabled"

    expiration {
      days = 30
    }
  }
}

# --- Elastic IP (stable public IP) ---
resource "aws_eip" "weather_intel" {
  instance = aws_instance.weather_intel.id
  domain   = "vpc"

  tags = {
    Name    = "weather-intel"
    Project = "weather-intel"
  }
}

output "public_ip" {
  value = aws_eip.weather_intel.public_ip
}

output "instance_id" {
  value = aws_instance.weather_intel.id
}

output "security_group_id" {
  value = aws_security_group.weather_intel.id
}
