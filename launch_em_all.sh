#!/usr/bin/env bash


parallel ::: "python -m plotter.eqe_plotter" "python -m plotter.it_plotter" "python -m plotter.iv_plotter" "python -m plotter.mppt_plotter" "python -m plotter.vt_plotter" 
