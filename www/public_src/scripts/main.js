/**
  * This is the main script for aiddataDET angular application.  This
  * file is responsible for:
  *   - Declaring and configuring the material design theme
  *   - Defining all routes and making necessary API requests
  */

angular.module('aiddataDET', ['ui.router', 'ui.bootstrap', 'ngMaterial', 'rzModule', 'ngAnimate'])
.config(function($stateProvider, $urlRouterProvider, $mdThemingProvider) {

  /*
   * ====================================================================
   * Material Design Theme Configuration
   * https://material.angularjs.org/latest/Theming/03_configuring_a_theme
   * ====================================================================
   */

  $mdThemingProvider.theme('default')
      .primaryPalette('blue-grey', {
        'default': '400',
        'hue-1': '100',
        'hue-2': '600',
        'hue-3': 'A100'
      })
      .accentPalette('green', {
        'default': '500',
        'hue-1': '100',
        'hue-2': '600',
        'hue-3': 'A100'
      })
      .warnPalette('deep-orange')
      .backgroundPalette('grey');

  /*
   * ===========================================
   * Routing and State Management using UI router
   * https://github.com/angular-ui/ui-router/wiki
   * ============================================
   */
  $urlRouterProvider.otherwise('/');

  $stateProvider
  .state('root', {
    abstract: true,
    resolve: {
      info: function(ajaxFactory) {
        return ajaxFactory.info()
          .then(function(results) {
            return results.data;
          });
      }
    },
    views: {
      '': {
        templateUrl: 'views/root.html',
        controller: 'RootCtrl'
      },
      'header@root': {
        templateUrl: 'views/components/root.header.html',
        controller: 'HeaderCtrl'
      },
      'cart@root': {
        templateUrl: 'views/components/root.cart.html',
        controller: 'CartCtrl'
      },
      'help@root': {
        templateUrl: 'views/components/root.help.html',
        controller: 'HelpCtrl'
      }
    }
  })
  .state('map', {
    parent: 'root',
    url: '/',
    params: { confirmation: { confirmed: false } },
    resolve: {
      boundaries: function(queryFactory) {
        return queryFactory.getBoundaries();
      }
    },
    onEnter: function() {
      this.params.confirmation.confirmed = false;
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
      'mapFrame@map': {
        template: '<div ng-class="{\'overlay\': showOverlay }" class="map"></div>',
        controller: 'MapFrameCtrl'
      }
    }
  })
  .state('search', {
    parent: 'root',
    url: '/search/:boundary/:subboundary',
    resolve: {
      boundary: function($log, $stateParams, queryFactory) {
        return queryFactory.getBoundaries()
          .then(function() {
            return queryFactory.setBoundary($stateParams.boundary, $stateParams.subboundary);
          });
      },
      datasets: function($log, $state, $stateParams, queryFactory, boundary) {
        return queryFactory.getDatasets(boundary.group)
          .then(function(data) { return data; })
          .catch(function() { return $state.go('map'); });
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/search.html'
      },
      'selectionText@search': {
        templateUrl: 'views/components/search.selectionText.html',
        controller: 'SelectionTextCtrl'
      },
      'datasetSelector@search': {
        templateUrl: 'views/components/search.datasetSelector.html',
        controller: 'DatasetSelectorCtrl'
      }
    }
  })
  .state('search.filters', {
    url: '/release/:dataset',
    templateUrl: 'views/components/search.filters.html',
    controller: 'FiltersCtrl',
    resolve: {
      filters: function(queryFactory, $log) {
        return queryFactory.filters;
      },
      dataset: function($state, $stateParams, datasets, routingService) {
        return routingService.verifyDataset($state, $stateParams, datasets);
      },
      filterOptions: function($log, $stateParams, dataset, queryFactory) {
        return queryFactory.updateFilters();
      }
    }
  })
  .state('search.options', {
    url: '/external/:dataset',
    templateUrl: 'views/components/search.options.html',
    controller: 'OptionsCtrl',
    resolve: {
      options: function(queryFactory, $log, datasets) {
        return queryFactory.options;
      },
      dataset: function($state, $stateParams, datasets, routingService) {
        return routingService.verifyDataset($state, $stateParams, datasets);
      }
    }
  })
  .state('checkout', {
    parent: 'root',
    url: '/checkout',
    resolve: {
      query: function($state, $stateParams, $timeout, $q, $http, queryFactory) {

        var boundary = queryFactory.getBoundary(),
            subboundary = queryFactory.getSubBoundary();

        if (!boundary.boundaryId || !subboundary.name) {
          return $timeout(function() { $state.go('map'); });
        }

        if (!queryFactory.querySize()) {
          return $timeout(function() {
            $state.go('search', {
              boundary: boundary.boundaryId,
              subboundary: subboundary.name
            });
          });
        }

        return true;
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/checkout.html'
      },
      'selections@checkout': {
        templateUrl: 'views/components/checkout.selections.html',
        controller: 'SelectionsCtrl'
      },
      'details@checkout': {
        templateUrl: 'views/components/checkout.details.html',
        controller: 'DetailsCtrl'
      }
    }
  })
  .state('login', {
    parent: 'root',
    url: '/login',
    templateUrl: 'views/pages/login.html',
    controller: 'LoginCtrl'
  })
  .state('requests', {
    parent: 'root',
    url: '/requests/:email',
    params: { notify: false },
    templateUrl: 'views/pages/requests.html',
    resolve: {
      requests: function(ajaxFactory, $stateParams) {
        return ajaxFactory.requests('email', $stateParams.email)
          .then(function(results) { return results.data; });
      },
      datasets: function($q, requests, queryFactory) {
        var datasets = _.map(requests, function(req) {
          return queryFactory.getDatasets(req.boundary.group);
        });
        return $q.all(datasets)
        .then(function(results) {
          return _.mapKeys(results, function(d, i) { return i; });
        });
      }
    },
    controller: 'RequestsCtrl'
  })
  .state('status', {
    parent: 'root',
    url: '/status/:id',
    resolve: {
      request: function(ajaxFactory, $stateParams) {
        return ajaxFactory.requests('id', $stateParams.id)
          .then(function(results) {
            return results.data[0];
          });
      },
      datasets: function(ajaxFactory, request) {
        return ajaxFactory.datasets(request.boundary.group)
          .then(function(results) { return results.data; });
      }
    },
    views: {
      '': {
        templateUrl: 'views/pages/status.html',
        controller: 'StatusCtrl'
      }
    }
  });

})
.run(function($rootScope, config) {
  $rootScope.config = config;

  /*
   * ================
   * Google Analytics
   * ================
   */

  (function(i, s, o, g, r, a, m){ i['GoogleAnalyticsObject'] = r;i[r] = i[r] || function(){
    (i[r].q = i[r].q || []).push(arguments); }, i[r].l = 1 * new Date();a = s.createElement(o),
  m = s.getElementsByTagName(o)[0];a.async = 1;a.src = g;m.parentNode.insertBefore(a, m);
  })(window, document, 'script', 'https://www.google-analytics.com/analytics.js', 'ga');

  ga('create', config.googleTrackingID, 'auto');
  ga('send', 'pageview');
});
