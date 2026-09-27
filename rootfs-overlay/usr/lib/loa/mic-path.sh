#!/bin/sh
# Built-in mics (handset-dmic-endfire from the stock mixer_paths_alor_mtp.xml):
# side-top SWR_MIC4 -> DEC2, side-bottom SWR_MIC8 -> DEC5, capture backend
# CODEC_DMA-LPAIF_RXTX-TX-3.
c() { amixer -c0 -q cset name="$1" "$2"; }
c "TX DEC2 MUX" SWR_MIC;  c "TX SMIC MUX2" SWR_MIC4; c "TX_AIF1_CAP Mixer DEC2" 1
c "ADC1 ChMap" SWRM_TX2_CH1; c "ADC1 MUX" CH1_AMIC1; c "TX0 MODE" ADC_LP
c "ADC1_MIXER Switch" 1; c "AMIC1_MIXER Switch" 1
c "TX DEC5 MUX" SWR_MIC;  c "TX SMIC MUX5" SWR_MIC8; c "TX_AIF1_CAP Mixer DEC5" 1
c "ADC3 ChMap" SWRM_TX3_CH1; c "ADC3 MUX" CH3_AMIC5; c "TX2 MODE" ADC_LP
c "ADC3_MIXER Switch" 1; c "AMIC5_MIXER Switch" 1
c "ADC1 Volume" 16; c "ADC3 Volume" 16
