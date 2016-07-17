angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'angucomplete-alt', 'ngMaterial'])
.config(function($stateProvider, $urlRouterProvider, $mdThemingProvider) {

  $mdThemingProvider.theme('default')
    .primaryPalette('blue-grey')
    .accentPalette('indigo', { 'default': '900' });

  $mdThemingProvider.alwaysWatchTheme(true);

  $urlRouterProvider.otherwise('/');

  $stateProvider.state('map', {
    url: '/',
    resolve: {
      boundaries: function(queryFactory) {
        return queryFactory.getBoundaries();
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/map.html'
      },
      'geographySearch@map': {
        templateUrl: 'views/components/map.geographySearch.html',
        controller: 'GeographySearchCtrl'
      },
      'zoomControls@map': {
        templateUrl: 'views/components/map.zoomControls.html',
        controller: 'ZoomControlsCtrl'
      },
      'map@map': {
        controller: 'MapCtrl'
      }
    }
  })
  .state('search', {
    url: '/search/:boundary/:subboundary',
    resolve: {
      boundaries: function($state, queryFactory) {
        return queryFactory.getBoundaries();
      },
      datasets: function($log, $q, $state, $stateParams, queryFactory) {
        return queryFactory.getDatasets($stateParams.boundary)
          .then(function(data) { return data; })
          .catch(function() { $state.go('map'); });
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/search.html'
      },
      'queryText@search': {
        templateUrl: 'views/components/search.queryText.html',
        controller: 'QueryTextCtrl'
      },
      'datasetSelector@search': {
        templateUrl: 'views/components/search.datasetSelector.html',
        controller: 'DatasetSelectorCtrl'
      },
      'filters@search': {
        templateUrl: 'views/components/search.filters.html',
        controller: 'FiltersCtrl'
      },
      'options@search': {
        templateUrl: 'views/components/search.options.html',
        controller: 'OptionsCtrl'
      }
    }
  })
  .state('submit', {
    url: '/submit',
    templateUrl: 'views/pages/submit.html'
  })
  .state('status', {
    url: '/status',
    templateUrl: 'views/pages/status.html'
  });
});
