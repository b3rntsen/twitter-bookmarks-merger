FROM nginx:alpine

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Create directory for Let's Encrypt challenge
RUN mkdir -p /var/www/certbot

# Expose ports
EXPOSE 80 443

