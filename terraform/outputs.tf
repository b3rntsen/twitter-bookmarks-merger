output "instance_id" {
  description = "ID of the EC2 instance"
  value       = aws_instance.web.id
}

output "instance_public_ip" {
  description = "Public IP address of the EC2 instance"
  value       = aws_eip.web_eip.public_ip
}

output "instance_public_dns" {
  description = "Public DNS name of the EC2 instance"
  value       = aws_instance.web.public_dns
}

output "application_url" {
  description = "URL to access the application"
  value       = "http://twitter.vibe.dethele.com:8000"
}

output "application_url_ip" {
  description = "URL to access the application via IP"
  value       = "http://${aws_eip.web_eip.public_ip}:8000"
}

output "route53_nameservers" {
  description = "Route 53 nameservers for vibe.dethele.com - configure these on one.com"
  value       = aws_route53_zone.vibe_dethele.name_servers
}

output "route53_zone_id" {
  description = "Route 53 hosted zone ID for vibe.dethele.com"
  value       = aws_route53_zone.vibe_dethele.zone_id
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = var.key_pair_name != "" ? "ssh -i ~/.ssh/${var.key_pair_name}.pem ec2-user@${aws_eip.web_eip.public_ip}" : "SSH not configured (no key_pair_name set)"
}

