# Load packages
pkgs <- c("magrittr", "targets", "tarchetypes", "crew")
pkgs_load <- sapply(pkgs, library, character.only = TRUE)

# Source user-defined functions
funs <- list.files("src/R", pattern = "*.R", full.name = TRUE) %>%
  lapply(source)

# Set option for targets
tar_option_set(
  packages   = pkgs,
  error      = "continue",
  memory     = "transient",
  controller = crew_controller_local(worker = 4),
  storage    = "worker",
  retrieval  = "worker",
  garbage_collection = TRUE
)

seed <- 1810


# Set the analysis pipeline
list(

  # List data files
  tar_target(fpath, "data/raw/articles.ris", format = "file"),

  # Read the data frame
  tar_target(tbl, readData(fpath)),

  # Deduplicate the data frame
  tar_target(tbl_dup, dedup(tbl, get_dup = TRUE)),
  tar_target(tbl_dedup, dedup(tbl)),

  # Write deduplicated data frame as a RIS file
  tar_target(
    dat_dedup,
    writeData(tbl_dedup, file = "data/processed/articles.ris"),
    format = "file"
  ),

  # Generate documentation
  tar_quarto(readme, "README.qmd", priority = 0)

)
