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

# Set MC and HC interpretation values
MC = [
    "Stress adversely affects mental health through emotional responses, leading to maladaptive coping strategies like substance use and social media engagement.",
    "Resilience acts as a protective buffer against stress, enabling active coping strategies and adaptation through personal attributes, ultimately fostering psychological well-being amid challenges."
]

HC1 = [
    "Stressful life events decompensate psychological resources and cause a long-lasting mental health impact, which in turn incite reward-seeking behavior",
    "An adequate resource is necessary to circumvent stressful life event and develop resilience"
]

HC2 = "Resilience plays a crucial role in mental health dynamics by acting as an adaptive function and coping mechanism that moderates the long-lasting impact of stress-induced strain and reward-seeking behavior, facilitating self-regulation, resource management, and the process of overcoming stress to enhance well-being and contribute to successful aging."

# Measure similarity between the MC and HC1 interpretation
for interpretation in zip(MC, HC1):
    embed = model.encode(interpretation, convert_to_tensor = True)
    sim = util.cos_sim(embed, embed)
    print(sim)

embed = model.encode(["".join(MC), "".join(HC1)])
sim = util.cos_sim(embed, embed)
print(sim)

# Measure similarity between the MC and HC2 interpretation
embed = model.encode(["".join(MC), HC2])
sim = util.cos_sim(embed, embed)
print(sim)

# Measure similarity between the HC1 and HC2 interpretation
embed = model.encode(["".join(HC1), HC2])
sim = util.cos_sim(embed, embed)
print(sim)
