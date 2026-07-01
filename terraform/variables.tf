variable "aws_region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  default     = "t3.small"
}

variable "ami_id" {
  description = "Ubuntu 24.04 AMI ID (us-east-1)"
  default     = "ami-0c7217cdde317cfec"
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
}

variable "admin_ip" {
  description = "Admin IP for SSH/Postgres access (CIDR format, e.g. 1.2.3.4/32)"
  type        = string
}
