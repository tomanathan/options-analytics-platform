resource "aws_glue_catalog_database" "bronze" {
  name         = "${var.project}_bronze"
  description  = "Iceberg tables for the bronze layer: raw daily options chains as ingested."
  location_uri = "s3://${aws_s3_bucket.lake.bucket}/bronze/"
}
