# Functions to parse the dataset

lsData <- function(path = "data/raw", ...) {
  #' List Data
  #'
  #' List all data file within `path` directory
  #'
  #' @param path A path of raw data directory, set to "data/raw" by default
  #' @return A list of complete relative path of each dataset

  filepath <- list.files(path, full.name = TRUE, recursive = TRUE, ...) %>%
    set_names(gsub(x = ., ".*_|\\w+/|\\.\\w*", ""))

  return(filepath)
}

readData <- function(fpath, ...) {
  #' Read Data Frame
  #'
  #' Read external tabular data as a tidy data frame
  #'
  #' @param fpath Path name of the file to parse
  #' @inheritDotParams readr::read_csv
  #' @return A tidy data frame

  tbl <- readr::read_csv(fpath, ...)

  return(tbl)
}
