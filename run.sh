#!/bin/bash

# 0) Add the SDE to PATH

cd /opt/bf-sde-9.12.0/
source /opt/tools/set_sde.bash

# 1) Stop any running processes associated with the ASIC daemon

killall bf_switchd
killall run_switchd

# 2) Load the ASIC control modules into the kernel

#load module if not loaded
bf_kdrv_mod_load $SDE_INSTALL

# 3) Compile the code
/$SDE/../tools/p4_build.sh ./source/p4_bareflow.p4

# 4) Start the switch
/$SDE/run_switchd.sh -p p4_bareflow 
# sleep 20


# 5) Open BFSHELL to enable the ports
/$SDE/run_bfshell.sh # For manual configuration
# /$SDE/run_bfshell.sh -f <configuration file name>


# 6) Terminate the process
#killall bf_switchd

