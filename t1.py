from settings import *

with open(testfile, encoding='utf8') as fp:
	for i, line in enumerate(fp):
		sentence = line.strip()
		print(i, sentence)
