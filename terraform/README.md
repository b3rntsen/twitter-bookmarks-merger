# Terraform Configuration for AWS Deployment

This directory contains Terraform configuration to deploy the Twitter Bookmarks application to AWS EC2 (free-tier eligible).

## DNS Setup

This Terraform configuration creates a Route 53 hosted zone for `vibe.dethele.com` and sets up `twitter.vibe.dethele.com` to point to the EC2 instance.

**Important**: After running `terraform apply`, you need to configure nameservers on one.com. See:
- **[ONECOM_DNS_QUICK_REFERENCE.md](ONECOM_DNS_QUICK_REFERENCE.md)** - Quick steps for one.com
- **[DNS_SETUP.md](DNS_SETUP.md)** - Detailed DNS setup guide

## Quick Start

1. **Set AWS credentials**:
   ```bash
   export AWS_ACCESS_KEY_ID=your-key
   export AWS_SECRET_ACCESS_KEY=your-secret
   ```

2. **Configure variables** (optional):
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   # Edit terraform.tfvars with your values
   ```

3. **Deploy**:
   ```bash
   cd ../scripts
   ./deploy.sh
   ```

4. **Upload application**:
   ```bash
   ./upload-to-aws.sh
   ```

5. **Destroy** (when done):
   ```bash
   ./destroy.sh
   ```

## Files

- `main.tf` - Main Terraform configuration (EC2, security groups, EIP)
- `variables.tf` - Input variables
- `outputs.tf` - Output values (IPs, URLs, etc.)
- `user_data.sh` - Script that runs on instance startup (installs Docker)
- `terraform.tfvars.example` - Example variables file

## Manual Terraform Commands

If you prefer using Terraform directly:

```bash
# Initialize
terraform init

# Plan
terraform plan

# Apply
terraform apply

# Outputs
terraform output

# Destroy
terraform destroy
```

## Variables

See `variables.tf` for all available variables. Key ones:

- `aws_region` - AWS region (default: us-east-1)
- `instance_type` - EC2 instance type (default: t2.micro, free-tier)
- `key_pair_name` - SSH key pair name (optional)
- `ssh_allowed_cidrs` - IPs allowed to SSH (default: 0.0.0.0/0)

## Outputs

After deployment, get outputs with:

```bash
terraform output
terraform output application_url
terraform output instance_public_ip
terraform output route53_nameservers  # Use these on one.com!
```

**Critical Steps After Deployment**:

1. **DNS Configuration**: Copy the `route53_nameservers` output and configure them on one.com to delegate `vibe.dethele.com` to AWS Route 53. See [ONECOM_DNS_QUICK_REFERENCE.md](ONECOM_DNS_QUICK_REFERENCE.md) for instructions.

2. **Google OAuth Configuration**: Add the production callback URL to Google Cloud Console:
   
   **Important**: Google OAuth requires a domain name (like `twitter.vibe.dethele.com`), not an IP address. IP addresses will be rejected.
   
   ```bash
   echo "Add this URL to Google Cloud Console:"
   echo "http://twitter.vibe.dethele.com:8000/accounts/google/login/callback/"
   ```
   - Go to: https://console.cloud.google.com/apis/credentials
   - Click your OAuth 2.0 Client ID
   - Add the domain URL above to "Authorized redirect URIs"
   - **Important**: 
     - Use your domain name (e.g., `twitter.vibe.dethele.com`), NOT the IP address
     - Include trailing slash (`/`)
     - Use `http://` (unless SSL is configured)
     - Google will reject IP addresses with "Invalid redirect: Must end with a public top-level domain"

