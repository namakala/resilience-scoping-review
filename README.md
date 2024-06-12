

# Getting started

Most of the works in this repository, especially the `R` scripts, should
be directly reproducible. You’ll need
[`git`](https://git-scm.com/downloads),
[`R`](https://www.r-project.org/),
[`quarto`](https://quarto.org/docs/download/), and more conveniently
[RStudio IDE](https://posit.co/downloads/) installed and running well in
your system. You simply need to fork/clone this repository using RStudio
by following [this tutorial, start right away from
`Step 2`](https://book.cds101.com/using-rstudio-server-to-clone-a-github-repo-as-a-new-project.html#step---2).
Using terminal in linux/MacOS, you can issue the following command:

``` bash
quarto tools install tinytex
```

This command will install `tinytex` in your path, which is required to
compile quarto documents as latex/pdf. Afterwards, in your RStudio
command line, you can copy paste the following code to setup your
working directory:

``` r
install.packages("renv") # Only need to run this step if `renv` is not installed
```

This step will install `renv` package, which will help you set up the
`R` environment. Please note that `renv` helps tracking, versioning, and
updating packages I used throughout the analysis.

``` r
renv::restore()
```

This step will read `renv.lock` file and install required packages to
your local machine. When all packages loaded properly (make sure there’s
no error at all), you *have to* restart your R session. At this point,
you need to export the data as `data.csv` and place it within the
`data/raw` directory. The directory structure *must* look like this:

``` bash
data
├── ...
├── raw
│   └── data.csv
└── ...
```

Then, you should be able to proceed with:

``` r
targets::tar_make()
```

This step will read `_targets.R` file, where I systematically draft all
of the analysis steps. Once it’s done running, you will find the
rendered document (either in `html` or `pdf`) inside the `draft`
directory.

# What’s this all about?

This is the functional pipeline for conducting statistical analysis. The
complete flow can be viewed in the following `mermaid` diagram:

``` mermaid
graph LR
  style Legend fill:#FFFFFF00,stroke:#000000;
  style Graph fill:#FFFFFF00,stroke:#000000;
  subgraph Legend
    direction LR
    x2db1ec7a48f65a9b([""Outdated""]):::outdated --- xb6630624a7b3aa0f([""Dispatched""]):::dispatched
    xb6630624a7b3aa0f([""Dispatched""]):::dispatched --- xf1522833a4d242c5([""Up to date""]):::uptodate
    xf1522833a4d242c5([""Up to date""]):::uptodate --- xd03d7c7dd2ddda2b([""Stem""]):::none
    xd03d7c7dd2ddda2b([""Stem""]):::none --- xeb2d7cac8a1ce544>""Function""]:::none
    xeb2d7cac8a1ce544>""Function""]:::none --- xbecb13963f49e50b{{""Object""}}:::none
  end
  subgraph Graph
    direction LR
    xe58bddd751ff431b(["fpath"]):::outdated --> xb24e8ba9befc2f2c(["tbl"]):::outdated
    x18b26034ab3a95e2>"readData"]:::uptodate --> xb24e8ba9befc2f2c(["tbl"]):::outdated
    xc11069275cfeb620(["readme"]):::dispatched --> xc11069275cfeb620(["readme"]):::dispatched
    x07bf962581a33ad1{{"funs"}}:::uptodate --> x07bf962581a33ad1{{"funs"}}:::uptodate
    x2f12837377761a1b{{"pkgs"}}:::uptodate --> x2f12837377761a1b{{"pkgs"}}:::uptodate
    x026e3308cd8be8b9{{"pkgs_load"}}:::uptodate --> x026e3308cd8be8b9{{"pkgs_load"}}:::uptodate
    x4d3ec24f81457d7f{{"seed"}}:::uptodate --> x4d3ec24f81457d7f{{"seed"}}:::uptodate
    xccc3e27231fd6e5d>"dedup"]:::uptodate --> xccc3e27231fd6e5d>"dedup"]:::uptodate
  end
  classDef outdated stroke:#000000,color:#000000,fill:#78B7C5;
  classDef dispatched stroke:#000000,color:#000000,fill:#DC863B;
  classDef uptodate stroke:#000000,color:#ffffff,fill:#354823;
  classDef none stroke:#000000,color:#000000,fill:#94a4ac;
  linkStyle 0 stroke-width:0px;
  linkStyle 1 stroke-width:0px;
  linkStyle 2 stroke-width:0px;
  linkStyle 3 stroke-width:0px;
  linkStyle 4 stroke-width:0px;
  linkStyle 7 stroke-width:0px;
  linkStyle 8 stroke-width:0px;
  linkStyle 9 stroke-width:0px;
  linkStyle 10 stroke-width:0px;
  linkStyle 11 stroke-width:0px;
  linkStyle 12 stroke-width:0px;
```
