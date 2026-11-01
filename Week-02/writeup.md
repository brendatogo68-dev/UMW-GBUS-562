## What I Built

I built a Prompt Lab web application that connects to Claude Sonnet 5 through the Anthropic API. The Prompt Lab allows users to enter prompts, receive responses, and export conversations as Markdown files.

Using the Prompt Lab, I completed four Wildframe Coffee Roasters tasks. Task 1 generated subscriber perk ideas, Task 2 created bean cards for new coffees, Task 3 generated customer service replies, and Task 4 analyzed pop-up location data to make a business recommendation. I exported each completed conversation and saved them as task-1.md, task-2.md, task-3.md, and task-4.md in the runs folder.

## Why This Approach

Task 1 - Technique: zero-shot

I chose zero-shot prompting because the task only required generating new subscriber perk ideas and did not require examples from the Brand Kit. The format requirements were simple and could be provided directly in the prompt.

Task 2 - Technique: one-shot

I chose one-shot prompting because the task required a specific bean card format. The Brand Kit provided one example card, which gave the model a template for the labels, order, and tone.

Task 3 - Technique: few-shot

I chose few-shot prompting because matching Wildframe's customer service voice was important. The multiple examples in the Brand Kit demonstrated the tone, style, and personality of the responses.

Task 4 - Technique: chain-of-thought

I chose chain-of-thought prompting because the task required calculations and comparison of several options. Asking the model to reason step by step helped ensure the recommendation was supported by the data and budget constraints.

## Example Run

````markdown
claude-sonnet-5

### You

You are writing bean cards for Wildframe Coffee Roasters.
 
Use this example as the model for format, labels, order, and tone:
 
HUILA, COLOMBIA
Roast: Medium
Tastes like: red apple, brown sugar, cocoa
Brew it: Pour-over or drip
Real talk: The coffee that converted our office's tea drinker. Mostly.
Create bean cards for the following coffees.


Requirements:
- Produce exactly three bean cards.
- Use the same labels and the same order as the example.
- Keep the tone warm, plainspoken, and slightly irreverent.
- Separate each card with one blank line.
 
Coffee 1:
Yirgacheffe, Ethiopia
Roast: Light
Notes: jasmine, lemon, bergamot
Best as: pour-over
 
Coffee 2:
Cerrado, BraziL
Roast: Medium-dark
Notes: peanut, milk chocolate, low acidity
Best as: espresso or French press

Coffee 3:
Chiapas, Mexico
Roast: Medium
Notes: almond, caramel, orange peel
Best as: drip or AeroPress

### Claude

YIRGACHEFFE, ETHIOPIA
Roast: Light
Tastes like: jasmine, lemon, bergamot
Brew it: Pour-over
Real talk: Smells like a flower shop, drinks like a wake-up call. Not for the "coffee should taste like coffee" crowd.

CERRADO, BRAZIL
Roast: Medium-dark
Tastes like: peanut, milk chocolate, low acidity
Brew it: Espresso or French press
Real talk: Smooth, nutty, and about as fussy as your favorite flannel shirt. Won't fight you in the morning.

CHIAPAS, MEXICO
Roast: Medium
Tastes like: almond, caramel, orange peel
Brew it: Drip or AeroPress
Real talk: Balanced enough to drink black, sweet enough to pretend you're fancy. We won't tell.
````

## Reflection

The results varied depending on the prompting technique used. For Task 1, zero-shot prompting worked well because the task was straightforward and only required generating creative subscriber perk ideas within a specific format. Task 2 benefited from one-shot prompting because the bean card example provided a clear template for structure, labels, and tone. Task 3 showed the value of few-shot prompting because the multiple customer service examples helped the model consistently match Wildframe's voice and personality. Task 4 was the most analytical task, making chain-of-thought prompting the best choice because it encouraged the model to perform calculations, compare alternatives, and justify its recommendation step by step.

The technique that made the biggest difference was chain-of-thought prompting in Task 4. Without step-by-step reasoning, the model might have overlooked important details such as the budget constraint or profitability calculations. The technique I am least sure about is zero-shot prompting for Task 1. While it produced good ideas, I could have experimented with a one-shot prompt using an example of a past subscriber perk to see whether the responses were more creative and better aligned with the Wildframe brand voice. Overall, the assignment showed that different tasks benefit from different prompting strategies, and selecting the appropriate technique can improve both accuracy and consistency.
