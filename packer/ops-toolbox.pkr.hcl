packer {
  required_plugins {
    docker = {
      source  = "github.com/hashicorp/docker"
      version = "~> 1"
    }
  }
}

variable "image_tag" {
  default = "latest"
}

source "docker" "ops-toolbox" {
  image  = "ubuntu:22.04"
  commit = true
  changes = [
    "LABEL maintainer=urlsnip",
    "LABEL description=URLSnip ops toolbox with kubectl helm terraform awscli",
    "WORKDIR /workspace",
    "ENV AWS_ACCESS_KEY_ID=test",
    "ENV AWS_SECRET_ACCESS_KEY=test",
    "ENV AWS_DEFAULT_REGION=us-east-1",
    "ENV AWS_ENDPOINT_URL=http://host-gateway:4566",
    "ENTRYPOINT [\"/bin/bash\"]"
  ]
}

build {
  name    = "ops-toolbox"
  sources = ["source.docker.ops-toolbox"]

  # System deps
  provisioner "shell" {
    inline = [
      "apt-get update -qq",
      "apt-get install -y curl unzip git jq wget gnupg lsb-release ca-certificates",
    ]
  }

  # AWS CLI
  provisioner "shell" {
    inline = [
      "curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip -o /tmp/awscliv2.zip",
      "unzip -q /tmp/awscliv2.zip -d /tmp",
      "/tmp/aws/install",
      "aws --version",
      "rm -rf /tmp/awscliv2.zip /tmp/aws"
    ]
  }

  # kubectl
  provisioner "shell" {
    inline = [
      "curl -fsSL https://dl.k8s.io/release/v1.34.0/bin/linux/arm64/kubectl -o /usr/local/bin/kubectl",
      "chmod +x /usr/local/bin/kubectl",
      "kubectl version --client"
    ]
  }

  # Helm
  provisioner "shell" {
    inline = [
      "curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash",
      "helm version"
    ]
  }

  # Terraform
  provisioner "shell" {
    inline = [
      "curl -fsSL https://releases.hashicorp.com/terraform/1.15.6/terraform_1.15.6_linux_arm64.zip -o /tmp/tf.zip",
      "unzip -q /tmp/tf.zip -d /usr/local/bin",
      "chmod +x /usr/local/bin/terraform",
      "terraform --version",
      "rm /tmp/tf.zip"
    ]
  }

  # k9s (K8s TUI)
  provisioner "shell" {
    inline = [
      "curl -fsSL https://github.com/derailed/k9s/releases/download/v0.32.5/k9s_Linux_arm64.tar.gz | tar -xz -C /usr/local/bin k9s",
      "chmod +x /usr/local/bin/k9s",
      "k9s version"
    ]
  }

  # Useful aliases
  provisioner "shell" {
    inline = [
      "echo 'alias k=kubectl' >> /root/.bashrc",
      "echo 'alias tf=terraform' >> /root/.bashrc",
      "echo 'alias kgp=\"kubectl get pods\"' >> /root/.bashrc",
      "echo 'alias kgn=\"kubectl get nodes\"' >> /root/.bashrc",
      "echo 'alias kga=\"kubectl get all\"' >> /root/.bashrc",
      "echo 'complete -F __start_kubectl k' >> /root/.bashrc"
    ]
  }

  post-processor "docker-tag" {
    repository = "urlsnip-ops-toolbox"
    tags       = [var.image_tag]
  }
}