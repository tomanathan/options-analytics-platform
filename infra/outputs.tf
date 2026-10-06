output "bucket_name" {
  description = "Data lake bucket; set OAP_S3_BUCKET to this value."
  value       = aws_s3_bucket.lake.bucket
}

output "bucket_arn" {
  description = "ARN of the data lake bucket."
  value       = aws_s3_bucket.lake.arn
}

output "glue_database_name" {
  description = "Glue Catalog database for bronze Iceberg tables; set OAP_GLUE_DATABASE to this value."
  value       = aws_glue_catalog_database.bronze.name
}

output "pipeline_user_name" {
  description = "IAM user the pipeline runs as; create its access key with the AWS CLI."
  value       = aws_iam_user.pipeline.name
}

output "pipeline_user_arn" {
  description = "ARN of the pipeline IAM user."
  value       = aws_iam_user.pipeline.arn
}
