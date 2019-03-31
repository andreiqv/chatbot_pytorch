import os
######### 
data_dir = '../data'
corpus_name = 'corpus'
save_dir = os.path.join(data_dir, "save")
#corpus_name = "corpus"
corpus = os.path.join(data_dir, corpus_name)
# Define path to new file
datafile = os.path.join(corpus, "formatted_movie_lines.txt")

MAX_LENGTH = 10  # Maximum sentence length to consider