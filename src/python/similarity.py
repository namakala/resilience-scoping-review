# Import modules
import pandas as pd
from sentence_transformers import SentenceTransformer, util

# Read dataset
tbl = pd.read_csv("data/raw/coding-excerpt.csv")

# Load a pre-trained SBERT model
model = SentenceTransformer("all-MiniLM-L6-v2")

# Create a placeholder for similarity measures
sims = {"MC_HC1": [], "MC_HC2": [], "HC1_HC2": []}

# Generate embeddings for each row
for index, row in tbl.iterrows():
    embed = model.encode(row, convert_to_tensor = True)
    sim = util.cos_sim(embed, embed)
    sims["MC_HC1"].append(sim[0, 1].item())
    sims["MC_HC2"].append(sim[0, 2].item())
    sims["HC1_HC2"].append(sim[1, 2].item())

# Transform the placeholder dictionary to a data frame
tbl_sim = pd.DataFrame(sims)

# Write a csv file
tbl_sim.to_csv("data/processed/coding-similarity.csv", sep = ",", index = False)
