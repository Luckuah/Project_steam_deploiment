variable "service_name" {
  type        = string
  description = "Name of the App Runner service"
}

variable "ecr_repo_url" {
  type        = string
  description = "URL of the ECR repository"
}

variable "subnet_ids" {
  type = list(string)
}

variable "sg_ids" {
  type = list(string)
}
