import React from "react";
import "../App.css";
import Post from "./post";
import Slider from "react-slick";

const settings = {
  dots: true,
  infinite: false,
  speed: 500,
  slidesToShow: 1,
  slidesToScroll: 1,
};

const SlideShow = ({ posts }) => (
  <div>
    <Slider {...settings}>
      {posts.map((post) => <Post data={post} />)}
    </Slider>
    <p className="tutorial">
      Arraste para o lado&ensp;<span className="tutorial-arrow">➜</span>
    </p>
  </div>
);

export default SlideShow;
