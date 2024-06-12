# Functions to parse the dataset

readData <- function(fpath, ...) {
  #' Read Data Frame
  #'
  #' Read external tabular data as a tidy data frame
  #'
  #' @param fpath Path name of the file to parse
  #' @inheritDotParams synthesisr::read_ref
  #' @return A tidy bibliography data frame

  tbl <- synthesisr::read_refs(fpath, ...) |> tibble::tibble()

  return(tbl)
}

writeData <- function(tbl, ...) {
  #' Write Data Frame
  #'
  #' Write data frame as a RIS file.
  #'
  #' @param tbl A tidy bibliography data frame
  #' @return An external file

  tbl |> data.frame() |> synthesisr::write_refs(...)

}

