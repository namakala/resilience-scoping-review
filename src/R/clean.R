# Functions to clean the dataset

findDuplicate <- function(str_list) {
  #' Find Duplicates
  #'
  #' Find duplicates from a given list of string.
  #'
  #' @param str_list A list of string
  #' @return A vector of boolean indicating the presence of duplicates

  dup <- str_list |> stringr::str_to_upper() |> duplicated()

  return(dup)
}

dedup <- function(tbl, get_dup = FALSE, conserve = FALSE, ...) {
  #' Deduplicate Bibliography
  #'
  #' Remove duplicate from a bibliography data frame.
  #'
  #' @param tbl A tidy bibliography data frame
  #' @param get_dup Return the duplicates
  #' @param conserve A boolean to use a more conservative approach. If
  #' `conserve` is set as `TRUE`, then the `AND` operator will be used,
  #' removing less duplicates. Otherwise, the `OR` operator will be used,
  #' removing more duplicates.
  #' @return A deduplicated tidy bibliography data frame

  # Find duplicates
  dup_doi    <- findDuplicate(tbl$doi)
  dup_title  <- findDuplicate(tbl$title)

  # Indicate duplication based on the DOI and/or title
  if (conserve) {
    duplicates <- dup_doi & dup_title
  } else {
    duplicates <- dup_doi | dup_title
  }

  # Remove duplicates
  if (get_dup) {
    duplicates <- !duplicates
  }

  sub_tbl <- tbl |> subset(!duplicates) |> dplyr::arrange(doi, author, year)

  return(sub_tbl)
}

