data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# No aws_iam_access_key here: its secret would sit in Terraform state. The runbook creates the key with the AWS CLI.
resource "aws_iam_user" "pipeline" {
  name = "${var.project}-pipeline"
}

data "aws_iam_policy_document" "pipeline" {
  statement {
    sid       = "LakeBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.lake.arn]
  }

  statement {
    sid = "LakeObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${aws_s3_bucket.lake.arn}/*"]
  }

  statement {
    sid = "BronzeCatalog"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:GetTable",
      "glue:GetTables",
      "glue:DeleteTable",
      "glue:GetPartitions",
      "glue:BatchCreatePartition",
      "glue:BatchDeletePartition",
    ]
    resources = [
      "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog",
      aws_glue_catalog_database.bronze.arn,
      "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.bronze.name}/*",
    ]
  }
}

resource "aws_iam_user_policy" "pipeline" {
  name   = "${var.project}-pipeline-lake-access"
  user   = aws_iam_user.pipeline.name
  policy = data.aws_iam_policy_document.pipeline.json
}
