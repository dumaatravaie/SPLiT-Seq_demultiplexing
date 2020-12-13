#!/usr/bin/env python

#####
#Description reframe the barcode extraction script to do the following.
#1. Improve speed by storing barcodes by position instead of string searching for them.
#2. Support sequence error handling by filtering and correcting barcodes on the fly using hamming distance.  
#   Filtering this way will improve speed by reducing reads carried forward to downstream steps.
#3. Store matepair information.
#4. Reduce the number of output files created. Depricate the single .fastq file per cell output format.
#####

import sys
import os
import argparse
import itertools
import json
#from Bio.Seq import Seq

#####
# Set consistent parameters here
Round1_barcode_staticSeq = "CATTCG"
Round2_barcode_staticSeq = "AATCCA"
Round3_barcode_staticSeq = "GTGGCC"
#####

#####
# Define "eprint" function to print to stderr
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)
#####

# Get arguments
parser = argparse.ArgumentParser()
parser.add_argument('-f', '--inputFastqF', required=False, help='Input a forward .fastq format file')
parser.add_argument('-r', '--inputFastqR', required=False, help='Input a reverse .fastq format file')
parser.add_argument('-o', '--outputFile', required=False, help='Name of the output file .fastq containg read hits')
parser.add_argument('-b', '--bin', required=False, help='Number of reads to process before saving to disc. Binning helps accomodate large input files')
parser.add_argument('-e', '--errorThreshold', required=False, help='Enter "0" or "1" if to indicate per barcode error threshold')
parser.add_argument('-p', '--performanceMetrics', required=False, action='store_true', help='Provide -p flag to turn on performance metrics reporting', default=False)
parser.add_argument('-t', '--readsPerCellThreshold', required=False, help='Provide a minimum reads per cell threshold for retaining a cell', default=1)
parser.add_argument('-v', '--verbose', required=False, action='store_true', help='Provide -v flag to turn on verbose progress reporting for each bin', default=False)
#parser.add_argument('-b1', '--barcode1', required=False, help='Provied the path to the Round1_barcodes_new5.txt file or a custom Round1 barcodes file'
#parser.add_argument('-d', '--directory', required=True, help='Directory containing the main SPLiT-Seq_demultiplexing materials')
args = parser.parse_args()


######
# Step1: Gather barcode information from provided barcodes.txt files
######
# Read in text files containing possible barcodes store them in a list
Round1_barcodes = []
Round2_barcodes = []
Round3_barcodes = []
Eight_BP_barcode = []

with open('Round1_barcodes_new5.txt', "r") as infile:
    for line in infile:
        Round1Barcode = line.rstrip()
        Round1_barcodes.append(line.rstrip())
        Eight_BP_barcode.append(Round1Barcode[8:16]) #Note this is the same for each round 

with open('Round2_barcodes_new4.txt', "r") as infile:
    for line in infile:
        Round2_barcodes.append(line.rstrip())

with open('Round3_barcodes_new4.txt', "r") as infile:
    for line in infile:
        Round3_barcodes.append(line.rstrip())

# Create a functon to compare barcodes
# Use hamming distance function from a stack overfow question I created "https://stackoverflow.com/questions/65258822/fast-python-short-dna-string-comparison/65259404#65259404"
def hamming(s1, s2):
    return sum(c1 != c2 for c1, c2 in zip(s1, s2))


######
# Create bin parameters
######
# Create a value used to bin the dataset
binIterator = int(int(args.bin) * 4)
eprint("binIterator is set to " + str(binIterator))
# Define workingBin
counter = 0
readCounterFinal = 0
workingBin = counter + binIterator

# Get the number of lines in the input file
with open(args.inputFastqF, "r") as infile:
    linesInInputFastq = sum(1 for line in infile)
    eprint("The linesInInputFastq value is set to " + str(linesInInputFastq))


######
# Build a class to store information from each read.
######
class FastQRead():
    def __init__(self, name, read, quality, lineNumber):
        self.name = name
        self.read = read
        self.quality = quality
        self.lineNumber = lineNumber

    def display_read(self):
        print("name = " + str(self.name) + "\n" \
            "read = " + str(self.read) + "\n" \
            "quality = " + str(self.quality) + "\n" \
            "lineNumber = " + str(self.lineNumber) + "\n", end='')

    def return_fastq(self):
        print(str(self.name) + "\n" \
            + str(self.read) + "\n" \
            + "+" + "\n" \
            + str(self.quality) + "\n", end='')

class barcodeRead(FastQRead):
    def __init__(self, name, read, quality, lineNumber, barcode1, barcode2, barcode3, umi):
        self.name = name
        self.read = read
        self.quality = quality
        self.lineNumber = lineNumber
        self.barcode1 = barcode1
        self.barcode2 = barcode2
        self.barcode3 = barcode3
        self.umi = umi

    def display_read(self):
        print("name = " + str(self.name) + "\n" \
            "read = " + str(self.read) + "\n" \
            "quality = " + str(self.quality) + "\n" \
            "lineNumber = " + str(self.lineNumber) + "\n" \
            "Barcodes = " + str(barcode1 + "_" + barcode2 + "_" + barcode3) + "\n"\
            "UMI = " + str(umi), end='')

    def return_fastq(self):
        readID = self.name
        readID_split = readID.split("/")
        noSpaceReadID = readID_split[0].replace(" ", "")
        print(str(noSpaceReadID.strip() + "_" + self.barcode1 + self.barcode2 + self.barcode3 + "_" + self.umi) + "\n" \
            + str(self.read) + "\n" \
            + "+" + "\n" \
            + str(self.quality) + "\n", end='')

######
# Create some lists that need to be outside of the loop in order to aggregate performance metrics
######
Total_barcodes_detected = []
Total_barcodes_passing_minReadThreshold = []


######
# Step2: Iterate through input fastqs in bins.
######
bin_counter = 0
for i in range(0,int(linesInInputFastq),int(binIterator)):
    # Create dictinaries used to store the parsed read information from the fastq files
    readsF = {}
    readsR = {}
    readsF_BC_UMI_dict = {}
    
    # Create empty lists
    filteredBarcode1 = []
    filteredBarcode2 = []
    filteredBarcode3 = []
    
    #startingline = int(bin_counter * binIterator)
    if (args.verbose == True):
        eprint("Processing range " + str(i) + " - " + str(int(i + binIterator)))

    # Iterate through the forward reads
    with open(args.inputFastqF, "r") as infile:
        line_ct1 = 0
        read_counter = 0 # To get the read counter to match we need to add 1. Each read = 4 lines.
        completeReadCounter = 0
        for line in itertools.islice(infile, i, int(i + binIterator)):
            if (line_ct1 % 4 == 0):
                lineName=str(line[0:].rstrip())
                completeReadCounter += 1
            if (line_ct1 % 4 == 1):
                lineRead=str(line[0:].rstrip())
                completeReadCounter += 1
            if (line_ct1 % 4 == 3):
                lineQuality=str(line[0:].rstrip())
                completeReadCounter += 1
            if (completeReadCounter == 3): 
                processedRead = FastQRead(name = lineName, \
                    read = lineRead, \
                    quality = lineQuality, \
                    lineNumber = read_counter)
                readsF[str(str(bin_counter) + "_" + str(read_counter))]=processedRead
                completeReadCounter = 0
                read_counter += 1
            line_ct1 += 1


    # Iterate through the reverse reads
    with open(args.inputFastqR, "r") as infile:
        line_ct1 = 0
        read_counter = 0
        completeReadCounter = 0
        for line in itertools.islice(infile, i, int(i + binIterator)):
            if (line_ct1 % 4 == 0):
                lineName=str(line[0:].rstrip())
                completeReadCounter += 1
            if (line_ct1 % 4 == 1):
                lineRead=str(line[0:].rstrip())
                lineReadUMI = lineRead[0:10]
                lineReadBarcode3 = lineRead[10:18]
                lineReadBarcode2 = lineRead[48:int(48+8)]
                lineReadBarcode1 = lineRead[86:int(86+8)]
                filteredBarcode1 = [s for s in Eight_BP_barcode if hamming(s, lineReadBarcode1) <= int(args.errorThreshold)]  # Match each extracted barcode to a greenlist of possible barcodes.  If a match within hamming distance of 1 is found move forward with that match (not the extracted sequence).
                filteredBarcode2 = [s for s in Eight_BP_barcode if hamming(s, lineReadBarcode2) <= int(args.errorThreshold)]
                filteredBarcode3 = [s for s in Eight_BP_barcode if hamming(s, lineReadBarcode3) <= int(args.errorThreshold)]
                completeReadCounter += 1
            if (line_ct1 % 4 == 3):
                lineQuality=str(line[0:].rstrip())
                completeReadCounter += 1
            if (completeReadCounter == 3):     
                if len(filteredBarcode1) == 0:  # The following if statments break the loop if a barcode does not pass the HD <=1 filter
                    line_ct1 += 1  # If the barcode observed does not match a barcode in our greenlist we escape the loop, count the line and reset the complete read counter.
                    completeReadCounter = 0
                    continue
                elif len(filteredBarcode2) == 0:
                    line_ct1 += 1
                    completeReadCounter = 0
                    continue
                elif len(filteredBarcode3) == 0:
                    line_ct1 += 1
                    completeReadCounter = 0
                    continue
                else:
                    processedRead = barcodeRead(name = lineName, \
                    read = lineRead, \
                    quality = lineQuality, \
                    lineNumber = int(read_counter + int(bin_counter * binIterator)), \
                    barcode1 = filteredBarcode1[0], \
                    barcode2 = filteredBarcode2[0], \
                    barcode3 = filteredBarcode3[0], \
                    umi = lineReadUMI)
                    readsR[str(str(bin_counter) + "_" + str(read_counter))]=processedRead
                    completeReadCounter = 0  # Reset the complete read counter to 0        
                read_counter += 1 # The read counter should progress even if a read does not satisfy the criteria for being retained. 
            line_ct1 += 1  # There are 4 lines for each read in the fastq file. The line counter needs to progress even if no "if" statements are satisfied.


######
# Step3: Transfer barcode from reverse read to forward read. Store new combined reads in dictionary as instances of class barcodedRead.
######
    #Pass Barcode information from reverse read to forward read. F and R parts of each read share the same key.
    # This needs to be done because in SPLiT-Seq the reverse read only contains the barcode
    # while the forward read contains the gene expression information.
    # So we need to create a read that contains the barcode information appended to the read name 
    # and the forward read information stored as the actual read.
    for key in readsR.keys():
        readF_BC_UMI = barcodeRead(name = readsF[key].name, \
            read = readsF[key].read, \
            quality = readsF[key].quality, \
            lineNumber = readsF[key].lineNumber, \
            barcode1 = readsR[key].barcode1, \
            barcode2 = readsR[key].barcode2, \
            barcode3 = readsR[key].barcode3, \
            umi = readsR[key].umi)
        readsF_BC_UMI_dict[key]=readF_BC_UMI

######
# Step4: Optional step to generate performance metrics.  (Omit to increase speed, as these metrics are not required output.)
######
    #eprint("starting step 4")
    if (args.performanceMetrics == True):
        if (args.verbose == True):
            eprint("Generating Performance Metrics")
        
        # The following block uses dictionaries to collect and store unique barcode combinations (CellIDs) and collect their associated UMIs (reads) in a list.
        # This information is used to output the number of cells identified, and number of reads identifed per cell.
        # These performance metrics can become the basis for applying thresholds to restrict the contents of the output .fastq file.
        counting_dict = {}
        for key in readsF_BC_UMI_dict.keys():
            bc1 = str(readsF_BC_UMI_dict[key].barcode1)
            bc2 = str(readsF_BC_UMI_dict[key].barcode2)
            bc3 = str(readsF_BC_UMI_dict[key].barcode3)
            bc_ID = str(bc1 + bc2 + bc3)
            UMI = str(readsF_BC_UMI_dict[key].umi)
            #if "N" not in str(BARCODE_PMmix):
            if (str(bc_ID) not in counting_dict.keys()):
                counting_dict[str(bc_ID)]=[]
                counting_dict[str(bc_ID)].append(str(UMI))
            else:
                counting_dict[str(bc_ID)].append(str(UMI))

        #Calculate number of cells detected
        totalCellsDetected = len(counting_dict.keys())

        #Calculate number of cells that meet the min reads-per-cell threshold
        filtered_counting_dict = {}
        for key in counting_dict.keys():
            if (len(counting_dict[key]) >= int(args.readsPerCellThreshold)):
                filtered_counting_dict[key]=counting_dict[key] 

        filteredCellsDetected = len(filtered_counting_dict.keys())
        
        if (args.verbose == True):
            eprint("Total barcodes detected" + " = " + str(totalCellsDetected))
            eprint("Barcodes meeting min read threshold" + " = " + str(filteredCellsDetected))

        Total_barcodes_detected.append(totalCellsDetected)
        Total_barcodes_passing_minReadThreshold.append(filteredCellsDetected)

        
######
# Step5: Write readF_BC_UMI reads to a .fastq file
######
    #file1 = open(str(args.outputFile + "/MergedCells_1.fastq", sep = ""), "a")
    #for key in readsF_BC_UMI_dict.keys():
    #    if readsF_BC_UMI_dict[key] is not None:
    #        file1.write(readsF_BC_UMI_dict[key].return_fastq())
    #file1.close() 

    # Here we can return the stored reads to the screen to confirm our read storage program is working as expected.
    for key in set(readsF_BC_UMI_dict.keys()):
        #readsF[key].return_fastq()
        readsF_BC_UMI_dict[key].return_fastq()
    
    bin_counter += 1
    # Flush stdout buffers
    #sys.stdout.flush()

# Provide final tally of reads containing barcodes and reads passing the threshold
eprint("The total number of barcodes detected was " + str(sum(Total_barcodes_detected)))
eprint("The total number of barcodes passing the minimum read threshold of " + str(args.readsPerCellThreshold) + " was " + str(sum(Total_barcodes_passing_minReadThreshold)))
