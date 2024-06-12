source("renv/activate.R")
# Disable tcltk pop-up menu, use text-based menu instead
options('menu.graphics' = F)

# Enable semi-transparency using cairo
setHook(
  packageEvent("grDevices", "onLoad"),
  function(...) grDevices::X11.options(type='cairo')
)

options(device='x11')
