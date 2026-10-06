variable "project" {
  description = "Short project name used as a prefix for resource names and the project tag."
  type        = string
  default     = "oap"
}

variable "aws_region" {
  description = "AWS region for every resource in this stack."
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Name of the data lake bucket. S3 bucket names are globally unique, so include something personal (initials plus a random suffix)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name)) && !can(regex("\\.\\.", var.bucket_name))
    error_message = "bucket_name must be 3-63 characters of lowercase letters, digits, dots and hyphens, start and end with a letter or digit, and contain no consecutive dots."
  }
}

variable "bronze_ia_transition_days" {
  description = "Days after which objects under bronze/ move to STANDARD_IA."
  type        = number
  default     = 30

  validation {
    condition     = var.bronze_ia_transition_days >= 30
    error_message = "bronze_ia_transition_days must be at least 30; S3 rejects STANDARD_IA transitions earlier than 30 days."
  }
}
