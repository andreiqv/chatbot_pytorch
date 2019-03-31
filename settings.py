import os
######### 
data_dir = '../data'
corpus_name = 'corpus'
#corpus_name = "corpus"
corpus = os.path.join(data_dir, corpus_name)
save_dir = os.path.join(data_dir, "save")
# Define path to new file
#datafile = os.path.join(corpus, "formatted_movie_lines.txt")
datafile = os.path.join("../data/rus_subs/train.utf")

MAX_LENGTH = 10  # Maximum sentence length to consider