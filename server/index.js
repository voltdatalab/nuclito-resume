import express from 'express';
import fetch from 'node-fetch';
const app = express();
const port = 8080;
import cors from 'cors';
import GhostContentAPI from '@tryghost/content-api';
import OpenAI from 'openai';
import dotenv from 'dotenv';
dotenv.config();


// Ghost API configuration
const api = new GhostContentAPI({
  url: 'https://nucleo.jor.br',
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
      const posts = await api.posts.browse({limit: 6, include: 'tags,authors'});
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
    let summariesHtml = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Post Summaries</title>
      <!-- Include Bootstrap CSS -->
      <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
    </head>
    <body>
      <div class="container">
        <div class="row g-3" id="masonry-layout">`; // Start the Bootstrap container and the first row

    // Iterate through each post, summarize it, and append its summary to the summariesHtml string
    for (const post of postsContent) {
      const summary = await summarizeContent(post.plainText);
      // Append this post's title, summary, and URL to the summariesHtml string using Bootstrap columns
      summariesHtml += `
        <div class="col-sm-6 col-md-4 mb-4"> <!-- Bootstrap column for 3 columns per row -->
          <div class="card">
            <h1 class="tit">${post.title}</h1>
            <p>${summary}</p>
            <a class="btn btn-primary button-tit" href="${post.url}">Quero saber mais</a>
          </div>
        </div>`;
    }

    summariesHtml += `
        </div> <!-- End of row -->
      </div> <!-- End of container -->
      <script>
      var elem = document.querySelector('#masonry-layout');
      var msnry = new Masonry(elem, {
        // Options
        itemSelector: '.col-sm-6', // Use your column classes here
        columnWidth: '.col-sm-6', // Or a fixed number
        percentPosition: true
      });
      </script>
    </body>
    </html>`;

    // Send the concatenated summaries as the response
    res.send(summariesHtml);
  } else {
    res.send(`<p>Erro, por favor tente de novo ou avise o Núcleo em comunidade@nucleo.jor.br</p>`);
  }
});


app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}`);
});

