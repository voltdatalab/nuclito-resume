import express from 'express';
import fetch from 'node-fetch';
const app = express();
const port = 8080;
import cors from 'cors';
import GhostContentAPI from '@tryghost/content-api';
import OpenAI from 'openai';
import dotenv from 'dotenv';

dotenv.config();

corsOptions = {
  origin: process.env.REACT_APP_CORS_ALLOWED_ORIGINS,
  optionsSuccessStatus: 200
}


// Ghost API configuration
const api = new GhostContentAPI({
  url: process.env.REACT_APP_GHOST_CONTENT_URL,
  key: process.env.REACT_APP_GHOST_CONTENT_API,
  version: "v5.0"
});

// OpenAI API configuration
const openai = new OpenAI({
  //apiKey: process.env['OPENAI_API_KEY'], // This is the default and can be omitted
  apiKey: process.env.REACT_APP_OPENAI_API_KEY,
});

// Function to fetch content from Ghost API
let content = []; // Initialize content as an empty array

// Utility function to convert HTML to plain text
function htmlToPlainText(html) {
  return html.replace(/<[^>]*>/g, '');
}

async function fetchPosts() {
  try {
      const posts = await api.posts.browse({limit: 5, include: 'tags,authors'});
      let content = []; // Use a local variable instead of a global one
      posts.forEach((post) => {
          // Convert HTML to plain text if necessary
          const plainText = post.html ? htmlToPlainText(post.html) : '';
          // Push an object with structured post data
          content.push({
              title: post.title,
              url: post.url,
              excerpt: post.excerpt,
              plainText: plainText,
          });
      });
      return content; // Return an array of objects
  } catch (err) {
      console.error(err);
      return []; // Return an empty array in case of an error
  }
}


//fetchPosts().then((content) => {
    // Work with populated content here
  //  console.log(content);
//});

// Function to summarize content using ChatGPT API
async function summarizeContent(content) {
  try {
    const response = await openai.chat.completions.create({
      messages: [{ role: 'user', content: `Faça um resumo deste texto em 3 bullet points, usando no máximo 20 palavras para cada bullet. Formate os bullets como uma lista em HTML: ${content}` }],
      model: 'gpt-4',
    });
    // Assuming the API returns a structure where the summary can be accessed like this:
    // This path may need adjustment based on the actual API response structure.
    const summaryText = response.choices[0].message.content;
    return summaryText; // Return the summary text
  } catch (err) {
    console.error(err);
    return ''; // Return an empty string or a meaningful error message in case of failure
  }
}

app.use(cors())

app.get('/', async (req, res) => {
    const postsContent = await fetchPosts(); // Fetches all posts
    if (postsContent && postsContent.length > 0) {
      let summariesHtml = ''; // Initialize an empty string to hold all summaries HTML
  
      // Iterate through each post, summarize it, and append its summary to the summariesHtml string
      for (const post of postsContent) {
        const summary = await summarizeContent(post.plainText);
        // Append this post's title, summary, and URL to the summariesHtml string
        summariesHtml += `<h1 class="tit">${post.title}</h1>
        <p>${summary}</p>
        <a class="button-tit" href="${post.url}">Quero saber mais</a><br><br>`;
      }
  
      // Send the concatenated summaries as the response
      res.send(summariesHtml);
    } else {
      res.send(`<p>Erro, por favor tente de novo ou avise o Núcleo em comunidade@nucleo.jor.br</p>`);
    }
  });

app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}`);
});

