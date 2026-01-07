terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Get the latest Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Security group for the EC2 instance
resource "aws_security_group" "web_sg" {
  name        = "${var.project_name}-web-sg"
  description = "Security group for Twitter Bookmarks web application"

  # HTTP access from anywhere
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP"
  }

  # HTTPS access from anywhere
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS"
  }

  # Django web server (port 8000) - for direct access or reverse proxy
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Django web server"
  }

  # SSH access (optional, for debugging)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidrs
    description = "SSH access"
  }

  # Allow all outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${var.project_name}-web-sg"
  }
}

# EC2 instance (default: t3.small with 2GB RAM for Docker builds)
resource "aws_instance" "web" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = var.key_pair_name
  vpc_security_group_ids = [aws_security_group.web_sg.id]
  
  # Free-tier eligible: 30GB gp3 storage (minimum required by AMI snapshot)
  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  # User data script to install Docker and run the app
  user_data = templatefile("${path.module}/user_data.sh", {
    project_name = var.project_name
  })

  user_data_replace_on_change = true

  tags = {
    Name        = "${var.project_name}-web"
    Project     = var.project_name
    Environment = var.environment
  }
}

# Elastic IP (optional, but useful for persistent IP)
resource "aws_eip" "web_eip" {
  instance = aws_instance.web.id
  domain   = "vpc"

  tags = {
    Name    = "${var.project_name}-eip"
    Project = var.project_name
  }
}

# Route 53 Hosted Zone for vibe.dethele.com
resource "aws_route53_zone" "vibe_dethele" {
  name = "vibe.dethele.com"

  tags = {
    Name    = "${var.project_name}-route53-zone"
    Project = var.project_name
  }
}

# A record for twitter.vibe.dethele.com pointing to the Elastic IP
resource "aws_route53_record" "twitter_vibe_dethele" {
  zone_id = aws_route53_zone.vibe_dethele.zone_id
  name    = "twitter.vibe.dethele.com"
  type    = "A"
  ttl     = 300
  records = [aws_eip.web_eip.public_ip]
}

# IAM Role for EC2 instance (for future use with ElastiCache, CloudWatch, etc.)
resource "aws_iam_role" "ec2_role" {
  name = "${var.project_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name    = "${var.project_name}-ec2-role"
    Project = var.project_name
  }
}

# IAM Instance Profile
resource "aws_iam_instance_profile" "ec2_profile" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2_role.name

  tags = {
    Name    = "${var.project_name}-ec2-profile"
    Project = var.project_name
  }
}

# Update EC2 instance to use IAM profile
resource "aws_instance" "web" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = var.key_pair_name
  vpc_security_group_ids = [aws_security_group.web_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2_profile.name
  
  # Free-tier eligible: 30GB gp3 storage (minimum required by AMI snapshot)
  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  # User data script to install Docker and run the app
  user_data = templatefile("${path.module}/user_data.sh", {
    project_name = var.project_name
  })

  user_data_replace_on_change = true

  tags = {
    Name        = "${var.project_name}-web"
    Project     = var.project_name
    Environment = var.environment
  }
}

